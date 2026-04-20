import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import TopBar from "./components/TopBar";
import LeftNav from "./components/LeftNav";
import Toast from "./components/Toast";

import Recommendations from "./views/Recommendations";
import RunDetail from "./views/RunDetail";
import StockAnalysis from "./views/StockAnalysis";
import Config from "./views/Config";
import NewsCenter from "./views/NewsCenter";

export default function App() {
  const [toast, setToast] = useState("");

  return (
    <BrowserRouter>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <TopBar onToast={setToast} />
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <LeftNav onConsume={() => setToast("已发起消费")} />
          <main style={{ flex: 1, overflow: "auto" }}>
            <Routes>
              <Route path="/"            element={<Recommendations />} />
              <Route path="/runs"        element={<RunDetail />} />
              <Route path="/runs/:id"    element={<RunDetail />} />
              <Route path="/stock"       element={<StockAnalysis onToast={setToast} />} />
              <Route path="/config"      element={<Config onToast={setToast} />} />
              <Route path="/news"        element={<NewsCenter onToast={setToast} />} />
            </Routes>
          </main>
        </div>
        <Toast message={toast} onDone={() => setToast("")} />
      </div>
    </BrowserRouter>
  );
}
