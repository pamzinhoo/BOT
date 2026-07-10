import { motion } from "framer-motion";

const ease = [0.16, 1, 0.3, 1] as const;

export default function Contact() {
  return (
    <section id="contato" className="relative bg-ink py-32 md:py-44 border-b border-line overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_100%,rgba(186,255,41,0.06),transparent_55%)]" />
      <div className="relative max-w-[1440px] mx-auto px-6 md:px-10 text-center">
        <motion.span
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="text-[12px] uppercase tracking-[0.2em] text-mist"
        >
          Pronto pra montar?
        </motion.span>

        <div className="overflow-hidden mt-6">
          <motion.h2
            initial={{ y: "100%" }}
            whileInView={{ y: "0%" }}
            viewport={{ once: true }}
            transition={{ duration: 0.9, ease }}
            className="font-display font-black text-white text-[11vw] md:text-[6vw] leading-[0.95] tracking-tight"
          >
            FALE COM A <span className="text-signal">COMPUBRÁS.</span>
          </motion.h2>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8, delay: 0.2, ease }}
          className="mt-12 flex flex-col md:flex-row items-center justify-center gap-4"
        >
          <a
            href="https://www.instagram.com/compubrastecnologia_/"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 bg-signal text-ink px-8 py-4 text-[13px] uppercase tracking-[0.12em] font-medium hover:bg-white transition-colors duration-300"
          >
            @compubrastecnologia_
            <span>→</span>
          </a>
          <span className="text-[13px] text-mist uppercase tracking-[0.1em]">
            Av. Paranavaí, 503 — Sala B, Maringá / PR
          </span>
        </motion.div>
      </div>
    </section>
  );
}
