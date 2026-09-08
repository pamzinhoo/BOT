import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AuditPage } from "./pages/AuditPage";
import { GiveawaysPage } from "./pages/GiveawaysPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PanelsPage } from "./pages/PanelsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StaffPage } from "./pages/StaffPage";
import { SystemPage } from "./pages/SystemPage";
import { TicketsPage } from "./pages/TicketsPage";

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/tickets" element={<TicketsPage />} />
        <Route path="/staff" element={<StaffPage />} />
        <Route path="/giveaways" element={<GiveawaysPage />} />
        <Route path="/settings/:section" element={<SettingsPage />} />
        <Route path="/panels" element={<PanelsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/system" element={<SystemPage />} />
      </Routes>
    </AppShell>
  );
}
