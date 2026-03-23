"""GRU-based event sequence encoder for AML detection.

Architecture:
  Event type embedding (10 types -> 8 dim)
  + 7 continuous features
  -> GRU (input=15, hidden=64, 1 layer, bidirectional)
  -> attention pooling over hidden states
  -> Linear(128, 1) -> sigmoid

Training: 5-fold OOF, same splits as pipeline.
Output: base_f_probability per user -> feeds into BlendEnsemble.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import average_precision_score


class EventDataset(Dataset):
    def __init__(self, user_ids, sequences, labels, max_len=200):
        self.user_ids = user_ids
        self.sequences = sequences
        self.labels = labels
        self.max_len = max_len

    def __len__(self):
        return len(self.user_ids)

    def __getitem__(self, idx):
        uid = self.user_ids[idx]
        label = self.labels[idx]
        if uid in self.sequences:
            type_ids, features, length = self.sequences[uid]
            length = min(length, self.max_len)
            padded_types = np.zeros(self.max_len, dtype=np.int64)
            padded_types[:length] = type_ids[:length]
            padded_feats = np.zeros((self.max_len, features.shape[1]), dtype=np.float32)
            padded_feats[:length] = features[:length]
        else:
            length = 1
            padded_types = np.zeros(self.max_len, dtype=np.int64)
            padded_feats = np.zeros((self.max_len, 7), dtype=np.float32)
        return padded_types, padded_feats, length, label


def collate_fn(batch):
    types, feats, lengths, labels = zip(*batch)
    return (
        torch.LongTensor(np.array(types)),
        torch.FloatTensor(np.array(feats)),
        torch.LongTensor(lengths),
        torch.FloatTensor(labels),
    )


class EventGRU(nn.Module):
    def __init__(self, n_types=10, embed_dim=8, feat_dim=7, hidden=64):
        super().__init__()
        self.type_embed = nn.Embedding(n_types, embed_dim)
        self.gru = nn.GRU(
            embed_dim + feat_dim, hidden, batch_first=True, bidirectional=True
        )
        self.attn = nn.Linear(hidden * 2, 1)
        self.head = nn.Sequential(
            nn.Linear(hidden * 2, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
        )

    def forward(self, types, feats, lengths):
        x = torch.cat([self.type_embed(types), feats], dim=-1)
        packed = pack_padded_sequence(
            x, lengths.cpu().clamp(min=1), batch_first=True, enforce_sorted=False
        )
        out, _ = self.gru(packed)
        out, _ = pad_packed_sequence(out, batch_first=True, total_length=types.size(1))
        attn_weights = torch.softmax(self.attn(out).squeeze(-1), dim=1)
        mask = (
            torch.arange(types.size(1), device=types.device).unsqueeze(0)
            < lengths.unsqueeze(1)
        )
        attn_weights = attn_weights * mask.float()
        attn_weights = attn_weights / (attn_weights.sum(dim=1, keepdim=True) + 1e-8)
        pooled = (out * attn_weights.unsqueeze(-1)).sum(dim=1)
        return self.head(pooled).squeeze(-1)


def train_gru_oof(sequences, user_ids, labels, fold_assignments, device="cuda"):
    """Train GRU 5-fold OOF, return per-user probabilities."""
    results = {}

    for fold_id, (train_uids, valid_uids) in enumerate(fold_assignments):
        print(f"  [GRU fold {fold_id}]", end=" ", flush=True)
        train_mask = [i for i, u in enumerate(user_ids) if u in train_uids]
        valid_mask = [i for i, u in enumerate(user_ids) if u in valid_uids]

        train_ds = EventDataset(
            [user_ids[i] for i in train_mask],
            sequences,
            [labels[i] for i in train_mask],
        )
        valid_ds = EventDataset(
            [user_ids[i] for i in valid_mask],
            sequences,
            [labels[i] for i in valid_mask],
        )

        train_dl = DataLoader(
            train_ds, batch_size=512, shuffle=True, collate_fn=collate_fn, num_workers=0
        )
        valid_dl = DataLoader(
            valid_ds, batch_size=1024, shuffle=False, collate_fn=collate_fn, num_workers=0
        )

        model = EventGRU().to(device)
        n_pos = sum(labels[i] for i in train_mask)
        n_neg = len(train_mask) - n_pos
        pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device).clamp(max=20.0)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=30)

        best_ap = 0
        patience = 5
        no_improve = 0
        best_state = None

        for epoch in range(30):
            model.train()
            for types, feats, lengths, lbls in train_dl:
                types = types.to(device)
                feats = feats.to(device)
                lengths = lengths.to(device)
                lbls = lbls.to(device)
                logits = model(types, feats, lengths)
                loss = criterion(logits, lbls)
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            scheduler.step()

            model.eval()
            all_probs, all_labels = [], []
            with torch.no_grad():
                for types, feats, lengths, lbls in valid_dl:
                    types = types.to(device)
                    feats = feats.to(device)
                    lengths = lengths.to(device)
                    probs = torch.sigmoid(model(types, feats, lengths)).cpu().numpy()
                    all_probs.extend(probs)
                    all_labels.extend(lbls.numpy())
            ap = average_precision_score(all_labels, all_probs)
            if ap > best_ap:
                best_ap = ap
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                no_improve = 0
            else:
                no_improve += 1
            if no_improve >= patience:
                break

        model.load_state_dict(best_state)
        model.eval()
        valid_probs = []
        with torch.no_grad():
            for types, feats, lengths, lbls in valid_dl:
                types = types.to(device)
                feats = feats.to(device)
                lengths = lengths.to(device)
                probs = torch.sigmoid(model(types, feats, lengths)).cpu().numpy()
                valid_probs.extend(probs)
        for i, vi in enumerate(valid_mask):
            results[user_ids[vi]] = float(valid_probs[i])

        print(f"AP={best_ap:.4f} (stopped@epoch={epoch + 1 - no_improve})")

    return results
