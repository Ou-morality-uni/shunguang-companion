import { createContext, useContext } from 'react';
export type PreviewResource = {
  kind: 'attachment' | 'artifact' | 'task' | 'history';
  id: string;
  title: string;
};
export type Preview = { id: string; title: string; close: () => void; trigger: HTMLElement | null };

export const PreviewContext = createContext<{
  active: string | null;
  host: HTMLDivElement | null;
  open: (value: Preview) => () => void;
  openResource: (value: PreviewResource, trigger?: HTMLElement | null) => void;
} | null>(null);

export function useResourcePreview() {
  return useContext(PreviewContext)?.openResource;
}
