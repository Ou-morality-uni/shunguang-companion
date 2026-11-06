import { MessageSquare } from 'lucide-react';
import { QQSpace } from './QQSpace';

export type EditionPage = 'qq';
export const editionNavigation = [{ key: 'qq' as const, label: 'QQ 接入', icon: MessageSquare }];
export function renderEditionPage(page: string) {
  return page === 'qq' ? <QQSpace /> : null;
}
