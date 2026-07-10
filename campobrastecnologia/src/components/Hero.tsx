import { motion } from "framer-motion";

const ease = [0.16, 1, 0.3, 1] as const;

export default function Hero() {
  return (
    <section id="top" className="relative min-h-[100svh] flex flex-col justify-end overflow-hidden border-b border-line">
      {/* grid backdrop */}
      <div
        className="absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_20%,rgba(186,255,41,0.08),transparent_60%)]" />

      <div className="relative max-w-[1440px] w-full mx-auto px-6 md:px-10 pt-40 pb-16">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 1, delay: 0.2 }}
          className="flex items-center gap-3 text-[12px] uppercase tracking-[0.2em] text-mist mb-8"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-signal animate-pulse" />
          Maringá · PR · Brasil
        </motion.div>

        <div className="overflow-hidden">
          <motion.h1
            initial={{ y: "110%" }}
            animate={{ y: "0%" }}
            transition={{ duration: 1, ease, delay: 0.3 }}
            className="font-display font-black text-white leading-[0.88] tracking-[-0.03em] text-[13vw] md:text-[7.4vw]"
          >
            SEU PC GAMER
          </motion.h1>
        </div>
        <div className="overflow-hidden">
          <motion.h1
            initial={{ y: "110%" }}
            animate={{ y: "0%" }}
            transition={{ duration: 1, ease, delay: 0.42 }}
            className="font-display font-black text-white leading-[0.88] tracking-[-0.03em] text-[13vw] md:text-[7.4vw]"
          >
            ESTÁ <span className="text-signal">AQUI.</span>
          </motion.h1>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease, delay: 0.75 }}
          className="mt-10 flex flex-col md:flex-row md:items-end justify-between gap-8 border-t border-line pt-8"
        >
          <p className="max-w-md text-[15px] md:text-[16px] leading-relaxed text-fog">
            A melhor loja de informática e tecnologia de Maringá. Máquinas
            montadas sob medida, peças selecionadas e assistência técnica
            especializada — engenharia, não achismo.
          </p>

          <div className="flex gap-4">
            <a
              href="#contato"
              className="group inline-flex items-center gap-2 bg-white text-ink px-6 py-3.5 text-[13px] uppercase tracking-[0.12em] font-medium hover:bg-signal transition-colors duration-300"
            >
              Falar no Instagram
              <span className="transition-transform duration-300 group-hover:translate-x-1">→</span>
            </a>
            <a
              href="#servicos"
              className="inline-flex items-center gap-2 border border-line px-6 py-3.5 text-[13px] uppercase tracking-[0.12em] text-white hover:border-white transition-colors duration-300"
            >
              Ver serviços
            </a>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
