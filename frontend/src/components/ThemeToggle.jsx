import Icon from './Icon.jsx';
import { useTheme } from '../lib/theme.jsx';

export default function ThemeToggle({ className = 'nav-theme', showLabel = false }) {
  const { theme, toggle } = useTheme();
  const dark = theme === 'dark';
  const label = dark ? 'Switch to light theme' : 'Switch to dark theme';
  return (
    <button
      type="button"
      className={className}
      onClick={toggle}
      title={label}
      aria-label={label}
      aria-pressed={dark}
    >
      <Icon name={dark ? 'sun' : 'moon'} size={showLabel ? 14 : 16} />
      {showLabel ? (dark ? 'Light' : 'Dark') : null}
    </button>
  );
}
