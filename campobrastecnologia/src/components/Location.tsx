import { motion } from "framer-motion";

const ease = [0.16, 1, 0.3, 1] as const;

export default function Location() {
  return (
    <section id="loja" className="relative bg-charcoal border-b border-line overflow-hidden">
      <div className="max-w-[1440px] mx-auto px-6 md:px-10 py-28 md:py-36 grid grid-cols-1 md:grid-cols-12 gap-12 md:gap-8">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.8, ease }}
          className="md:col-span-5"
        >
          <span className="text-[12px] uppercase tracking-[0.16em] text-mist">Localização</span>
          <h2 className="font-display font-bold text-white text-[9vw] md:text-[3.4vw] leading-[1] tracking-tight mt-4 mb-8">
            Visite a loja em Maringá.
          </h2>
          <p className="text-fog text-[15px] leading-relaxed max-w-sm">
            Atendimento presencial para montagem, upgrade e assistência
            técnica. Fale antes pelo Instagram e garanta prioridade no
            atendimento.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.8, ease, delay: 0.15 }}
          className="md:col-span-7 border border-line bg-ink p-8 md:p-12"
        >
          <div className="grid grid-cols-2 gap-8 text-[13px]">
            <div>
              <span className="block text-mist uppercase tracking-[0.12em] mb-2">Endereço</span>
              <span className="block text-white text-[16px] leading-relaxed">
                Av. Paranavaí, 503 — Sala B
              </span>
            </div>
            <div>
              <span className="block text-mist uppercase tracking-[0.12em] mb-2">Cidade</span>
              <span className="block text-white text-[16px] leading-relaxed">
                Maringá — PR
              </span>
            </div>
            <div>
              <span className="block text-mist uppercase tracking-[0.12em] mb-2">CEP</span>
              <span className="block text-white text-[16px] leading-relaxed">
                87015-360
              </span>
            </div>
            <div>
              <span className="block text-mist uppercase tracking-[0.12em] mb-2">Instagram</span>
              <a
                href="https://www.instagram.com/compubrastecnologia_/"
                target="_blank"
                rel="noreferrer"
                className="block text-signal text-[16px] leading-relaxed hover:underline"
              >
                @compubrastecnologia_
              </a>
            </div>
          </div>

          <div className="mt-10 pt-8 border-t border-line">
            <a
              href="https://www.google.com/maps/search/?api=1&query=Avenida+Paranavaí+503+Sala+B+Maringá+PR"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 text-[13px] uppercase tracking-[0.12em] text-white border border-line px-6 py-3.5 hover:border-signal hover:text-signal transition-colors"
            >
              Abrir no mapa
              <span>→</span>
            </a>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
