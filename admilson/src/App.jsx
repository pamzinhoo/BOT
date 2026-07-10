import { useEffect, useRef, useState } from 'react'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'

const NAV_LINKS = [
  { id: 'home', label: 'Home' },
  { id: 'servicos', label: 'Serviços' },
  { id: 'portfolio', label: 'Portfólio' },
  { id: 'sobre', label: 'Sobre' },
  { id: 'processos', label: 'Processos' },
  { id: 'estatisticas', label: 'Estatísticas' },
  { id: 'contato', label: 'Contato' },
]

const SERVICOS = [
  {
    n: '01',
    titulo: 'Consultoria e Treinamentos',
    desc: 'Consultoria para Microempreendedores Individuais (MEI) e facilitação de treinamentos em oratória e trabalho em equipe. Atuação em capacitação de Informática no CIEE, PUCPR e FCV — Faculdade Cidade Verde.',
    tags: ['MEI', 'Oratória', 'Trabalho em Equipe', 'CIEE · PUCPR · FCV'],
  },
  {
    n: '02',
    titulo: 'Tecnologia da Informação',
    desc: 'Coordenação técnica, projeto e instalação de redes corporativas, suporte a links dedicados via rádio e fibra óptica, administração de infraestrutura de escritórios regionais e monitoramento remoto.',
    tags: ['Redes Corporativas', 'Infraestrutura', 'Suporte Técnico', 'Monitoramento Remoto'],
  },
  {
    n: '03',
    titulo: 'Gestão Administrativa',
    desc: 'Definição de políticas administrativas, implantação de procedimentos operacionais e organização de processos internos para apoiar a gestão empresarial.',
    tags: ['Políticas', 'Processos Internos', 'Apoio à Gestão'],
  },
  {
    n: '04',
    titulo: 'Gestão de Pessoas',
    desc: 'Técnicas administrativas, gerenciamento de pessoas e desenvolvimento de equipes voltados à evolução dos processos organizacionais.',
    tags: ['Equipes', 'Desenvolvimento', 'Processos Organizacionais'],
  },
  {
    n: '05',
    titulo: 'Gestão de Documentos',
    desc: 'Administração documental e organização de infraestrutura administrativa — redes de dados, elétricas e telefônicas.',
    tags: ['Documentos', 'Redes de Dados', 'Infraestrutura'],
  },
  {
    n: '06',
    titulo: 'Consultoria Jurídica',
    desc: 'Maior embasamento jurídico para tomada de decisões empresariais mais seguras e eficientes.',
    tags: ['Jurídico', 'Tomada de Decisão'],
  },
]

const PORTFOLIO = [
  { nome: 'CF Log', area: 'Logística em Transportes' },
  { nome: 'Prefeitura de Maringá', area: 'Administração Pública' },
]

const MISSAO_ITENS = [
  'Modernização administrativa',
  'Novas práticas de gestão',
  'Melhoria dos processos organizacionais',
  'Evolução das atividades operacionais',
  'Desenvolvimento dos níveis gerenciais',
  'Tomadas de decisão mais eficientes',
]

const DIFERENCIAIS = [
  'Experiência prática em gestão e tecnologia',
  'Forte atuação em treinamento e capacitação',
  'Experiência no setor público e privado',
  'Conhecimento em infraestrutura completa de TI',
  'Atuação multidisciplinar — gestão, tecnologia e pessoas',
  'Processo de trabalho estruturado em seis etapas',
]

const PROCESSOS = [
  { n: '01', titulo: 'Mapeamento', desc: 'Levantamento do cenário e das necessidades do cliente.' },
  { n: '02', titulo: 'Planejamento', desc: 'Definição de estratégias e etapas do projeto.' },
  { n: '03', titulo: 'Validação', desc: 'Alinhamento das soluções propostas com o cliente.' },
  { n: '04', titulo: 'Produção', desc: 'Execução prática das soluções definidas.' },
  { n: '05', titulo: 'Testes', desc: 'Verificação de qualidade e ajustes finos.' },
  { n: '06', titulo: 'Implantação', desc: 'Entrega e colocação em operação da solução.' },
]

const ESTATISTICAS = [
  { valor: 500, sufixo: '+', label: 'Acessos no site' },
  { valor: 40, sufixo: '+', label: 'Clientes' },
  { valor: 120, sufixo: '+', label: 'Projetos concluídos' },
  { valor: 80, sufixo: '+', label: 'Treinamentos concluídos' },
]

const fadeUp = {
  hidden: { opacity: 0, y: 32 },
  show: { opacity: 1, y: 0, transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1] } },
}

const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
}

function Reveal({ children, className = '', as: Tag = motion.div, ...props }) {
  return (
    <Tag
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-80px' }}
      className={className}
      {...props}
    >
      {children}
    </Tag>
  )
}

function Eyebrow({ children, dark }) {
  return (
    <div className="flex items-center gap-3 mb-6">
      <span className={`h-px w-8 ${dark ? 'bg-brass' : 'bg-brass'}`} />
      <span className="font-display text-[11px] tracking-[0.28em] uppercase text-brass">
        {children}
      </span>
    </div>
  )
}

function Counter({ valor, sufixo }) {
  const [n, setN] = useState(0)
  const ref = useRef(null)
  const done = useRef(false)

  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting && !done.current) {
            done.current = true
            const start = performance.now()
            const dur = 1500
            const tick = (t) => {
              const p = Math.min((t - start) / dur, 1)
              const eased = 1 - Math.pow(1 - p, 3)
              setN(Math.floor(eased * valor))
              if (p < 1) requestAnimationFrame(tick)
              else setN(valor)
            }
            requestAnimationFrame(tick)
          }
        })
      },
      { threshold: 0.4 }
    )
    if (ref.current) io.observe(ref.current)
    return () => io.disconnect()
  }, [valor])

  return (
    <span ref={ref}>
      {n}
      {sufixo}
    </span>
  )
}

function Nav({ onNav, active }) {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const go = (id) => {
    setOpen(false)
    onNav(id)
  }

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-500 ${
        scrolled ? 'bg-ink/85 backdrop-blur-md border-b border-line' : 'bg-transparent border-b border-transparent'
      }`}
    >
      <div className="max-w-[1400px] mx-auto px-6 md:px-10 h-20 flex items-center justify-between">
        <button
          onClick={() => go('home')}
          className="flex items-center gap-3 group"
        >
          <span className="w-8 h-8 border border-brass/60 flex items-center justify-center">
            <span className="w-1.5 h-1.5 bg-brass" />
          </span>
          <span className="font-display text-sm tracking-[0.18em] uppercase text-bone">
            InLocu <span className="text-mute">Soluções</span>
          </span>
        </button>

        <nav className="hidden lg:flex items-center gap-1">
          {NAV_LINKS.map((l) => (
            <button
              key={l.id}
              onClick={() => go(l.id)}
              className={`relative px-4 py-2 font-display text-[12px] tracking-[0.14em] uppercase transition-colors ${
                active === l.id ? 'text-bone' : 'text-mute hover:text-bone'
              }`}
            >
              {l.label}
              {active === l.id && (
                <motion.span
                  layoutId="nav-dot"
                  className="absolute left-1/2 -translate-x-1/2 -bottom-0.5 w-1 h-1 bg-brass rounded-full"
                />
              )}
            </button>
          ))}
        </nav>

        <button
          onClick={() => go('contato')}
          className="hidden lg:inline-flex items-center gap-2 border border-line px-5 py-2.5 font-display text-[12px] tracking-[0.14em] uppercase text-bone hover:border-brass hover:text-brass transition-colors"
        >
          Fale Conosco
        </button>

        <button
          className="lg:hidden flex flex-col gap-1.5 p-2"
          aria-label="menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className={`w-6 h-px bg-bone transition-transform ${open ? 'translate-y-[3.5px] rotate-45' : ''}`} />
          <span className={`w-6 h-px bg-bone transition-transform ${open ? '-translate-y-[3.5px] -rotate-45' : ''}`} />
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="lg:hidden overflow-hidden bg-ink border-b border-line"
          >
            <div className="px-6 py-4 flex flex-col">
              {NAV_LINKS.map((l) => (
                <button
                  key={l.id}
                  onClick={() => go(l.id)}
                  className="text-left py-3 font-display text-sm tracking-[0.1em] uppercase text-bone-dim hover:text-brass border-b border-line-soft last:border-0"
                >
                  {l.label}
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  )
}

function Hero({ onNav }) {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  const y = useTransform(scrollYProgress, [0, 1], [0, 160])
  const opacity = useTransform(scrollYProgress, [0, 0.8], [1, 0])

  const words = ['Soluções', 'que', 'colocam', 'sua', 'empresa', 'em', 'movimento.']

  return (
    <section id="home" ref={ref} className="relative min-h-screen flex flex-col justify-center overflow-hidden bg-ink">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 -right-40 w-[560px] h-[560px] rounded-full bg-brass/[0.06] blur-3xl" />
        <div className="absolute top-1/3 -left-40 w-[420px] h-[420px] rounded-full bg-charcoal-2 blur-3xl" />
        <div
          className="absolute inset-0 opacity-[0.035]"
          style={{
            backgroundImage:
              'linear-gradient(to right, #f3f1ec 1px, transparent 1px), linear-gradient(to bottom, #f3f1ec 1px, transparent 1px)',
            backgroundSize: '64px 64px',
          }}
        />
      </div>

      <motion.div style={{ y, opacity }} className="relative max-w-[1400px] mx-auto w-full px-6 md:px-10 pt-32 pb-20">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
          className="flex items-center gap-3 mb-10"
        >
          <span className="h-px w-8 bg-brass" />
          <span className="font-display text-[11px] tracking-[0.28em] uppercase text-brass">
            Gestão · Consultoria · Treinamentos · TI
          </span>
        </motion.div>

        <h1 className="font-display font-medium text-[13vw] md:text-[7.2vw] leading-[0.96] tracking-[-0.03em] text-bone max-w-5xl">
          {words.map((w, i) => (
            <motion.span
              key={w + i}
              initial={{ opacity: 0, y: '100%' }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.9, delay: 0.15 + i * 0.06, ease: [0.16, 1, 0.3, 1] }}
              className={`inline-block mr-[0.28em] ${w === 'movimento.' ? 'text-brass' : ''}`}
            >
              {w}
            </motion.span>
          ))}
        </h1>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.8 }}
          className="mt-12 grid md:grid-cols-[1fr_auto] gap-10 items-end"
        >
          <p className="text-bone-dim text-base md:text-lg leading-relaxed max-w-xl">
            Levamos às empresas soluções para superar adversidades e contratempos relacionados à
            gestão administrativa — por meio de consultoria, treinamentos e tecnologia.
          </p>

          <div className="flex gap-3">
            <button
              onClick={() => onNav('contato')}
              className="inline-flex items-center gap-2 bg-bone text-ink px-7 py-3.5 font-display text-[12px] tracking-[0.14em] uppercase hover:bg-brass transition-colors"
            >
              Fale Conosco
            </button>
            <button
              onClick={() => onNav('servicos')}
              className="inline-flex items-center gap-2 border border-line px-7 py-3.5 font-display text-[12px] tracking-[0.14em] uppercase text-bone hover:border-brass hover:text-brass transition-colors"
            >
              Ver Serviços
            </button>
          </div>
        </motion.div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4, duration: 0.8 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2"
      >
        <span className="font-display text-[10px] tracking-[0.2em] uppercase text-mute">Scroll</span>
        <motion.span
          animate={{ y: [0, 8, 0] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
          className="w-px h-8 bg-gradient-to-b from-mute to-transparent"
        />
      </motion.div>
    </section>
  )
}

function ServicoRow({ s }) {
  const [hover, setHover] = useState(false)
  return (
    <Reveal as={motion.div}>
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        className="group border-b border-line py-8 md:py-10 grid md:grid-cols-[100px_1fr_auto] gap-4 md:gap-10 items-start cursor-default transition-colors"
      >
        <span className="font-display text-mute text-sm tracking-[0.1em]">{s.n}</span>

        <div>
          <h3 className="font-display text-2xl md:text-[32px] leading-tight text-bone group-hover:text-brass transition-colors">
            {s.titulo}
          </h3>
          <motion.div
            initial={false}
            animate={{ height: hover ? 'auto' : 0, opacity: hover ? 1 : 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <p className="text-bone-dim text-sm md:text-base leading-relaxed max-w-xl pt-4">{s.desc}</p>
            <div className="flex flex-wrap gap-2 pt-5">
              {s.tags.map((t) => (
                <span
                  key={t}
                  className="text-[11px] tracking-[0.06em] uppercase text-brass border border-brass/30 px-3 py-1"
                >
                  {t}
                </span>
              ))}
            </div>
          </motion.div>
        </div>

        <span
          className={`hidden md:flex w-10 h-10 border border-line items-center justify-center transition-all ${
            hover ? 'border-brass bg-brass text-ink rotate-45' : 'text-mute'
          }`}
        >
          +
        </span>
      </div>
    </Reveal>
  )
}

function Servicos() {
  return (
    <section id="servicos" className="relative bg-ink py-28 md:py-36">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid md:grid-cols-[1fr_auto] gap-8 items-end mb-16">
          <Reveal>
            <Eyebrow>O que fazemos</Eyebrow>
            <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone">
              Nossos Serviços
            </h2>
          </Reveal>
          <Reveal>
            <p className="text-mute text-sm max-w-xs md:text-right">
              Seis frentes de atuação — de consultoria e treinamentos à infraestrutura completa de TI.
            </p>
          </Reveal>
        </div>

        <div>
          {SERVICOS.map((s) => (
            <ServicoRow key={s.n} s={s} />
          ))}
        </div>
      </div>
    </section>
  )
}

function Portfolio() {
  return (
    <section id="portfolio" className="relative bg-charcoal py-28 md:py-36 border-y border-line">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <Reveal className="mb-16">
          <Eyebrow>Quem confia</Eyebrow>
          <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone">Portfólio</h2>
        </Reveal>

        <div className="grid md:grid-cols-2 gap-px bg-line">
          {PORTFOLIO.map((p, i) => (
            <Reveal
              key={p.nome}
              className="group relative bg-charcoal p-10 md:p-14 min-h-[280px] flex flex-col justify-between overflow-hidden"
            >
              <span className="font-display text-[10px] tracking-[0.24em] uppercase text-mute">
                Case {String(i + 1).padStart(2, '0')}
              </span>
              <div>
                <h3 className="font-display text-3xl md:text-5xl text-bone tracking-[-0.02em] group-hover:text-brass transition-colors">
                  {p.nome}
                </h3>
                <p className="mt-3 text-bone-dim text-sm tracking-[0.02em]">{p.area}</p>
              </div>
              <div className="absolute right-8 bottom-8 w-10 h-10 border border-line-soft flex items-center justify-center text-mute group-hover:border-brass group-hover:text-brass group-hover:rotate-45 transition-all">
                →
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function Sobre() {
  return (
    <section id="sobre" className="relative bg-ink py-28 md:py-36">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <Reveal className="mb-16 max-w-3xl">
          <Eyebrow>Quem somos</Eyebrow>
          <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone mb-8">
            Sobre a InLocu
          </h2>
          <p className="font-display text-xl md:text-3xl leading-snug text-bone-dim">
            "Levar às empresas soluções para superar{' '}
            <span className="text-brass">adversidades e contratempos</span> relacionados à gestão
            administrativa — por meio de consultoria, treinamentos e tecnologia."
          </p>
        </Reveal>

        <div className="grid md:grid-cols-2 gap-16 md:gap-24 pt-8 border-t border-line">
          <Reveal className="pt-12">
            <span className="font-display text-[11px] tracking-[0.28em] uppercase text-mute mb-8 block">
              Conceitos
            </span>
            <ul className="space-y-0">
              {MISSAO_ITENS.map((item, i) => (
                <li
                  key={item}
                  className="flex items-baseline gap-4 py-4 border-b border-line-soft text-bone-dim text-sm md:text-base"
                >
                  <span className="font-display text-mute text-xs">{String(i + 1).padStart(2, '0')}</span>
                  {item}
                </li>
              ))}
            </ul>
          </Reveal>

          <Reveal className="pt-12">
            <span className="font-display text-[11px] tracking-[0.28em] uppercase text-mute mb-8 block">
              Diferenciais
            </span>
            <ul className="space-y-0">
              {DIFERENCIAIS.map((item, i) => (
                <li
                  key={item}
                  className="flex items-baseline gap-4 py-4 border-b border-line-soft text-bone-dim text-sm md:text-base"
                >
                  <span className="font-display text-brass text-xs">{String(i + 1).padStart(2, '0')}</span>
                  {item}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

function Processos() {
  return (
    <section id="processos" className="relative bg-charcoal py-28 md:py-36 border-t border-line overflow-hidden">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <Reveal className="mb-16 max-w-2xl">
          <Eyebrow>Como trabalhamos</Eyebrow>
          <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone">
            Nossos Processos
          </h2>
        </Reveal>

        <motion.div
          variants={stagger}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: '-80px' }}
          className="grid md:grid-cols-6 gap-6 md:gap-4 relative"
        >
          <div className="hidden md:block absolute top-8 left-0 right-0 h-px bg-line" />
          {PROCESSOS.map((p) => (
            <motion.div key={p.n} variants={fadeUp} className="relative pt-0 md:pt-16 group">
              <div className="hidden md:flex absolute top-0 left-0 w-4 h-4 rounded-full bg-charcoal border-2 border-line group-hover:border-brass group-hover:bg-brass transition-colors" />
              <span className="font-display text-4xl text-line group-hover:text-brass/40 transition-colors block mb-3">
                {p.n}
              </span>
              <h3 className="font-display text-lg text-bone mb-2">{p.titulo}</h3>
              <p className="text-mute text-sm leading-relaxed">{p.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}

function Estatisticas() {
  return (
    <section id="estatisticas" className="relative bg-ink py-28 md:py-36 border-t border-line">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <Reveal className="mb-16 max-w-2xl">
          <Eyebrow>Números</Eyebrow>
          <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone">
            Estatísticas
          </h2>
        </Reveal>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-line">
          {ESTATISTICAS.map((e) => (
            <Reveal key={e.label} className="bg-ink p-8 md:p-10">
              <div className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-brass">
                <Counter valor={e.valor} sufixo={e.sufixo} />
              </div>
              <p className="mt-3 text-mute text-xs md:text-sm tracking-[0.04em] uppercase">{e.label}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function Contato() {
  const [sent, setSent] = useState(false)
  return (
    <section id="contato" className="relative bg-charcoal py-28 md:py-36 border-t border-line">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10">
        <div className="grid lg:grid-cols-2 gap-16">
          <Reveal>
            <Eyebrow>Vamos conversar</Eyebrow>
            <h2 className="font-display text-4xl md:text-6xl tracking-[-0.02em] text-bone mb-10">
              Fale Conosco
            </h2>

            <div className="space-y-0">
              {[
                ['Empresa', 'InLocu Soluções'],
                ['Cidade', 'Maringá – PR'],
                ['Telefone', '(44) 9836-8391'],
                ['E-mail', 'contato@inlocusolucoes.com.br'],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between items-center py-5 border-b border-line-soft">
                  <span className="font-display text-[11px] tracking-[0.2em] uppercase text-mute">{label}</span>
                  <span className="text-bone text-sm md:text-base">{value}</span>
                </div>
              ))}
            </div>
          </Reveal>

          <Reveal>
            <form
              className="flex flex-col gap-8"
              onSubmit={(ev) => {
                ev.preventDefault()
                setSent(true)
                ev.target.reset()
                setTimeout(() => setSent(false), 4000)
              }}
            >
              {[
                { name: 'nome', label: 'Seu nome', type: 'text' },
                { name: 'email', label: 'Seu e-mail', type: 'email' },
              ].map((f) => (
                <label key={f.name} className="block">
                  <span className="font-display text-[11px] tracking-[0.2em] uppercase text-mute">{f.label}</span>
                  <input
                    type={f.type}
                    required
                    className="w-full bg-transparent border-b border-line focus:border-brass outline-none py-3 text-bone placeholder:text-mute transition-colors"
                  />
                </label>
              ))}
              <label className="block">
                <span className="font-display text-[11px] tracking-[0.2em] uppercase text-mute">Mensagem</span>
                <textarea
                  required
                  rows={3}
                  className="w-full bg-transparent border-b border-line focus:border-brass outline-none py-3 text-bone resize-none transition-colors"
                />
              </label>

              <button
                type="submit"
                className="mt-2 inline-flex items-center justify-center gap-2 bg-bone text-ink px-7 py-4 font-display text-[12px] tracking-[0.14em] uppercase hover:bg-brass transition-colors w-full md:w-auto"
              >
                {sent ? 'Mensagem enviada ✓' : 'Enviar Mensagem'}
              </button>
              <p className="text-mute text-xs">MVP — integração de envio ainda não conectada.</p>
            </form>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

function Footer({ onNav }) {
  return (
    <footer className="bg-ink border-t border-line py-10">
      <div className="max-w-[1400px] mx-auto px-6 md:px-10 flex flex-col md:flex-row justify-between items-center gap-4">
        <span className="font-display text-[11px] tracking-[0.2em] uppercase text-mute">
          © {new Date().getFullYear()} InLocu Soluções — Maringá, PR
        </span>
        <button
          onClick={() => onNav('home')}
          className="font-display text-[11px] tracking-[0.2em] uppercase text-mute hover:text-brass transition-colors"
        >
          Voltar ao topo ↑
        </button>
      </div>
    </footer>
  )
}

function App() {
  const [active, setActive] = useState('home')

  useEffect(() => {
    const sections = NAV_LINKS.map((l) => document.getElementById(l.id)).filter(Boolean)
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) setActive(e.target.id)
        })
      },
      { rootMargin: '-45% 0px -45% 0px' }
    )
    sections.forEach((s) => io.observe(s))
    return () => io.disconnect()
  }, [])

  const handleNav = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="bg-ink">
      <Nav onNav={handleNav} active={active} />
      <Hero onNav={handleNav} />
      <Servicos />
      <Portfolio />
      <Sobre />
      <Processos />
      <Estatisticas />
      <Contato />
      <Footer onNav={handleNav} />
    </div>
  )
}

export default App
