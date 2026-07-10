import Nav from "./components/Nav";
import Hero from "./components/Hero";
import Marquee from "./components/Marquee";
import Services from "./components/Services";
import Location from "./components/Location";
import Contact from "./components/Contact";
import Footer from "./components/Footer";

export default function App() {
  return (
    <div className="bg-ink min-h-screen">
      <div className="noise" />
      <Nav />
      <Hero />
      <Marquee />
      <Services />
      <Location />
      <Contact />
      <Footer />
    </div>
  );
}
