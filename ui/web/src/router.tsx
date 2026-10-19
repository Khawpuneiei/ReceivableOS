// A small hash router: "#/invoice/case_1" -> ["invoice", "case_1"]. Hash URLs work on any static host.

import { useEffect, useState, type ReactNode } from "react";

const parse = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);

export function useRoute(): string[] {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const onChange = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
      // Move focus to the new page's heading so keyboard and screen-reader users land on it.
      requestAnimationFrame(() => document.querySelector<HTMLElement>("main h1")?.focus());
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const go = (path: string) => {
  window.location.hash = path;
};

export function Link({ to, className, children, ...rest }: { to: string; className?: string; children: ReactNode; "aria-current"?: "page" }) {
  return (
    <a href={`#${to}`} className={className} {...rest}>
      {children}
    </a>
  );
}
