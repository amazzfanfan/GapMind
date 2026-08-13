import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

/**
 * P0.5-4: light/dark theme preference with localStorage persistence.
 * The antd ConfigProvider algorithm switches in main.tsx; the html
 * `data-theme` attribute drives any hand-written CSS overrides.
 */

const STORAGE_KEY = "gm-theme";

interface ThemeContextValue {
  isDark: boolean;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({ isDark: false, toggleTheme: () => {} });

function readInitial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "dark";
  } catch {
    return false;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [isDark, setIsDark] = useState<boolean>(() => readInitial());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, isDark ? "dark" : "light");
    } catch {
      // ignore storage failures (private mode / quota)
    }
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  }, [isDark]);

  return (
    <ThemeContext.Provider value={{ isDark, toggleTheme: () => setIsDark((v) => !v) }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
