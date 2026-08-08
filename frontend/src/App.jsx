import { Routes, Route } from 'react-router-dom';
// import GovBanner from './components/GovBanner.jsx'; // temporarily disabled
import Header from './components/Header.jsx';
import Footer from './components/Footer.jsx';
import { TourProvider } from './components/Tour.jsx';
import SearchPage from './pages/SearchPage.jsx';
import ResultsPage from './pages/ResultsPage.jsx';
import DetailPage from './pages/DetailPage.jsx';
import CoveragePage from './pages/CoveragePage.jsx';
import AnalyticsPage from './pages/AnalyticsPage.jsx';

export default function App() {
  return (
    <TourProvider>
      {/* <GovBanner /> temporarily disabled */}
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/cola/:id" element={<DetailPage />} />
          <Route path="/coverage" element={<CoveragePage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="*" element={<SearchPage />} />
        </Routes>
      </main>
      <Footer />
    </TourProvider>
  );
}
