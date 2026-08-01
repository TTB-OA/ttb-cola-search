import { Routes, Route } from 'react-router-dom';
import GovBanner from './components/GovBanner.jsx';
import Header from './components/Header.jsx';
import Footer from './components/Footer.jsx';
import SearchPage from './pages/SearchPage.jsx';
import ResultsPage from './pages/ResultsPage.jsx';
import DetailPage from './pages/DetailPage.jsx';

export default function App() {
  return (
    <>
      <GovBanner />
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/cola/:id" element={<DetailPage />} />
          <Route path="*" element={<SearchPage />} />
        </Routes>
      </main>
      <Footer />
    </>
  );
}
