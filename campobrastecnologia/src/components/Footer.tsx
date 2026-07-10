export default function Footer() {
  return (
    <footer className="bg-ink py-8">
      <div className="max-w-[1440px] mx-auto px-6 md:px-10 flex flex-col md:flex-row items-center justify-between gap-4 text-[12px] uppercase tracking-[0.1em] text-mist">
        <span>© {new Date().getFullYear()} Compubrás Tecnologia — Maringá / PR</span>
        <span className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-signal" />
          Loja de informática · Assistência técnica
        </span>
      </div>
    </footer>
  );
}
