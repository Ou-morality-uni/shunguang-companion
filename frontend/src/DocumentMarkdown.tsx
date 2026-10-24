import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeSourceUrl } from './api';

export function DocumentMarkdown({ text }: { text: string }) {
  return (
    <div className="document-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          img: ({ alt }) => <span>〔图片：{alt || '请查看原文件'}〕</span>,
          a: ({ href, children }) => (
            <a href={safeSourceUrl(href)} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
