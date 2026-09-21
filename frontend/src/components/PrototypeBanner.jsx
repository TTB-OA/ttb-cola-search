import { useLocation } from 'react-router-dom';
import Icon from './Icon.jsx';

const REPO_URL = (import.meta.env.VITE_GITHUB_REPO_URL || 'https://github.com/TTB-OA/ttb-cola-search').replace(/\/+$/, '');
const FEEDBACK_EMAIL = import.meta.env.VITE_FEEDBACK_EMAIL || 'opendata@ttb.gov';

function buildFeedback(location) {
  const route = `${location.pathname}${location.search}${location.hash}`;
  const pageUrl = typeof window !== 'undefined' ? window.location.href : route;
  const subject = `COLA Search prototype feedback: ${location.pathname}`;
  const context = [
    `- Page: ${pageUrl}`,
    `- Route: ${route}`,
    `- Reported: ${new Date().toISOString()}`,
    `- Browser: ${typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown'}`,
    `- Viewport: ${typeof window !== 'undefined' ? `${window.innerWidth}x${window.innerHeight}` : 'unknown'}`,
  ];
  const body = [
    '### What happened / what would you change?',
    '',
    '',
    '### Steps to reproduce (if reporting a bug)',
    '1. ',
    '2. ',
    '',
    '---',
    '_Automatically captured context_',
    '',
    ...context,
  ].join('\n');
  const issueParams = new URLSearchParams({ title: subject, body });
  const emailBody = [
    'What happened / what would you change?',
    '',
    '',
    'Steps to reproduce (if reporting a bug):',
    '1. ',
    '2. ',
    '',
    '---',
    'Automatically captured context',
    ...context,
  ].join('\r\n');
  return {
    issueUrl: `${REPO_URL}/issues/new?${issueParams.toString()}`,
    emailUrl: `mailto:${FEEDBACK_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(emailBody)}`,
  };
}

export default function PrototypeBanner() {
  const location = useLocation();
  const { issueUrl, emailUrl } = buildFeedback(location);
  return (
    <div className="prototype-banner" role="status">
      <div className="wrap">
        <Icon name="info" size={16} />
        <span>
          <b>Prototype</b> — this tool is a prototype to assess capabilities. Historical data is not completely available, and all findings should be verified against source systems (COLAs Online). The tool is not intended for public use.
        </span>
        <span className="feedback-links">
          <span className="feedback-label">Feedback:</span>
          <a
            href={issueUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Opens GitHub with an issue prefilled with the page you're viewing"
          >
            <Icon name="external" size={13} />
            GitHub issue
          </a>
          <a href={emailUrl} title={`Opens your email client with a message to ${FEEDBACK_EMAIL}`}>
            <Icon name="mail" size={13} />
            Email
          </a>
        </span>
      </div>
    </div>
  );
}
