import { motion } from "framer-motion";

const ease = [0.16, 1, 0.3, 1] as const;

const SERVICES = [
  {
    index: "01",
    title: "PCs Gamer sob medida",
    desc:
      "Máquinas montadas peça a peça para o seu uso: streaming, competitivo, criação de conteúdo ou produtividade pesada. Cada configuração é pensada para o orçamento e o objetivo do cliente — sem gordura, sem gargalo.",
    specs: ["Consultoria de build", "Peças selecionadas", "Teste de estresse antes da entrega"],
  },
  {
    index: "02",
    title: "Assistência técnica especializada",
    desc:
      "Diagnóstico preciso, manutenção preventiva e corretiva em notebooks, desktops e periféricos. Formatação, upgrade, limpeza física, troca de pasta térmica e recuperação de sistema — feito por quem entende de hardware.",
    specs: ["Diagnóstico técnico", "Upgrade de hardware", "Suporte pós-serviço"],
  },
];

export default function Services() {
  return (
    <section id="servicos" className="relative bg-ink py-28 md:py-36 border-b border-line">
      <div className="max-w-[1440px] mx-auto px-6 md:px-10">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.8, ease }}
          className="flex items-end justify-between mb-16 md:mb-24"
        >
          <h2 className="font-display font-bold text-white text-[10vw] md:text-[4.2vw] leading-[0.95] tracking-tight">
            O que fazemos
          </h2>
          <span className="hidden md:block text-[12px] uppercase tracking-[0.16em] text-mist mb-2">
            Serviços — 02
          </span>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-line">
          {SERVICES.map((s, i) => (
            <motion.article
              key={s.index}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.7, ease, delay: i * 0.12 }}
              className="bg-ink p-8 md:p-12 flex flex-col justify-between min-h-[420px] group"
            >
              <div>
                <span className="font-display text-[13px] text-signal tracking-[0.1em]">
                  {s.index}
                </span>
                <h3 className="font-display font-bold text-white text-[28px] md:text-[34px] leading-[1.05] mt-6 mb-5 tracking-tight">
                  {s.title}
                </h3>
                <p className="text-fog text-[15px] leading-relaxed max-w-md">
                  {s.desc}
                </p>
              </div>

              <ul className="mt-10 pt-6 border-t border-line space-y-2">
                {s.specs.map((spec) => (
                  <li key={spec} className="flex items-center gap-3 text-[13px] text-mist uppercase tracking-[0.08em]">
                    <span className="w-1 h-1 bg-mist group-hover:bg-signal transition-colors" />
                    {spec}
                  </li>
                ))}
              </ul>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  );
}
