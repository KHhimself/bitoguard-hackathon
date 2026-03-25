import { HEX } from "./constants";

export function RiskMeter({ score, size = "lg" }: { score: number; size?: "lg" | "md" }) {
  const getColor = (s: number) => s >= 80 ? HEX.danger : s >= 60 ? HEX.warning : s >= 40 ? "#FFE066" : HEX.safe;
  const r = size === "lg" ? 54 : 36;
  const dim = size === "lg" ? 140 : 96;
  const stroke = size === "lg" ? 10 : 7;
  const fontSize = size === "lg" ? "text-3xl" : "text-xl";
  const circumference = 2 * Math.PI * r;

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: dim, height: dim }}>
      <svg width={dim} height={dim} className="-rotate-90">
        <circle cx={dim / 2} cy={dim / 2} r={r} fill="none" stroke="#E8ECF2" strokeWidth={stroke} />
        <circle
          cx={dim / 2} cy={dim / 2} r={r} fill="none"
          stroke={getColor(score)} strokeWidth={stroke}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 1s ease" }}
        />
      </svg>
      <span className={`absolute ${fontSize} font-bold`} style={{ color: getColor(score) }}>{Math.round(score)}</span>
    </div>
  );
}
