const ITEMS = [
  "MONTAGEM SOB MEDIDA",
  "ASSISTÊNCIA ESPECIALIZADA",
  "PEÇAS ORIGINAIS",
  "SUPORTE EM MARINGÁ",
  "PERFORMANCE REAL",
];

export default function Marquee() {
  const loop = [...ITEMS, ...ITEMS];
  return (
    <div className="relative border-b border-line bg-charcoal overflow-hidden py-5">
      <div className="flex whitespace-nowrap animate-[marquee_28s_linear_infinite]">
        {loop.map((item, i) => (
          <span
            key={i}
            className="font-display font-bold text-[14px] md:text-[16px] tracking-[0.08em] text-mist mx-6 flex items-center gap-6"
          >
            {item}
            <span className="w-1.5 h-1.5 bg-signal rounded-full" />
          </span>
        ))}
      </div>
      <style>{`
        @keyframes marquee {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
