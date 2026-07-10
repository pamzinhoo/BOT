import { useEffect, useState } from "react";
import { motion } from "framer-motion";

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <motion.header
      initial={{ y: -40, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      className={`fixed top-0 inset-x-0 z-50 transition-colors duration-500 ${
        scrolled ? "bg-ink/85 backdrop-blur-md border-b border-line" : "bg-transparent border-b border-transparent"
      }`}
    >
      <div className="max-w-[1440px] mx-auto flex items-center justify-between px-6 md:px-10 h-16 md:h-20">
        <a href="#top" className="font-display font-extrabold tracking-tight text-[15px] md:text-[17px] text-white flex items-center gap-2">
          <span className="inline-block w-2 h-2 bg-signal" />
          COMPUBRÁS<span className="text-mist font-medium">.TEC</span>
        </a>

        <nav className="hidden md:flex items-center gap-10 text-[13px] uppercase tracking-[0.14em] text-fog">
          <a href="#servicos" className="hover:text-white transition-colors">Serviços</a>
          <a href="#assistencia" className="hover:text-white transition-colors">Assistência</a>
          <a href="#loja" className="hover:text-white transition-colors">Loja</a>
          <a href="#contato" className="hover:text-white transition-colors">Contato</a>
        </nav>

        <a
          href="https://www.instagram.com/compubrastecnologia_/"
          target="_blank"
          rel="noreferrer"
          className="text-[12px] uppercase tracking-[0.14em] border border-line px-4 py-2 text-white hover:bg-signal hover:text-ink hover:border-signal transition-colors duration-300"
        >
          @compubrastecnologia_
        </a>
      </div>
    </motion.header>
  );
}
