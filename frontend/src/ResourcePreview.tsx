import { useCallback, useEffect, useState } from 'react';
import { request, type FileTask, type HistorySource } from './api';
import type { PreviewResource } from './PreviewContext';
import { TaskDetails } from './FileTasks';
import { DocumentResult } from './DocumentControls';
import { DocumentMarkdown } from './DocumentMarkdown';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCompanionAudio } from './useAudioQueue';
import { useAnnotations } from './Annotations';
import { OfficePreview } from './OfficePreview';

export function ResourcePreview({
  resource,
  onSettings,
}: {
  resource: PreviewResource;
  onSettings?: () => void;
}) {
  const annotations = useAnnotations();
  return resource.kind === 'history' ? (
    <HistoryResource resource={resource} />
  ) : resource.kind === 'task' ? (
    <TaskResource resource={resource} onSettings={onSettings} />
  ) : (annotations || /\.(docx|pptx|pdf|png|jpe?g|webp|bmp|tiff?|gif)$/i.test(resource.title)) &&
    /\.(docx|xlsx|pptx|pdf|png|jpe?g|webp|bmp|tiff?|gif|md|txt)$/i.test(resource.title) ? (
    <OfficePreview resource={resource} />
  ) : (
    <FileResourcePreview resource={resource} />
  );
}

function HistoryResource({ resource }: { resource: PreviewResource }) {
  const [source, setSource] = useState<HistorySource | null>(null),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void request<HistorySource>(`/memories/history/${encodeURIComponent(resource.id)}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) setSource(value);
      })
      .catch((failure: Error) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [resource.id]);
  return (
    <div className="history-source-preview">
      {error ? (
        <p role="status">{error}</p>
      ) : source ? (
        <>
          <p className="space-note">
            {source.title} · {source.role === 'user' ? '你的原话' : '当时的回复'} ·{' '}
            {new Date(source.time).toLocaleString('zh-CN')}
          </p>
          <DocumentMarkdown text={source.text} />
        </>
      ) : (
        <p role="status">正在读取来源…</p>
      )}
    </div>
  );
}

function TaskResource({ resource, onSettings }: { resource: PreviewResource; onSettings?: () => void }) {
  const [task, setTask] = useState<FileTask | null>(null);
  const [notice, setNotice] = useState('');
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const result = await request<FileTask>(`/work/tasks/${encodeURIComponent(resource.id)}`, { signal });
      if (!signal?.aborted) {
        setTask(result);
        setNotice('');
      }
    },
    [resource.id],
  );
  useEffect(() => {
    const abort = new AbortController();
    let polling = false;
    async function poll() {
      if (polling || abort.signal.aborted || document.hidden) return;
      polling = true;
      try {
        await refresh(abort.signal);
      } catch (error) {
        if (!abort.signal.aborted) setNotice((error as Error).message);
      } finally {
        polling = false;
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 1500);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [refresh]);
  return (
    <>
      {notice && <p role="status">{notice}</p>}
      {task ? (
        <TaskDetails
          task={task}
          enter={false}
          onChanged={refresh}
          onSettings={onSettings ?? (() => {})}
          attachments={[]}
        />
      ) : (
        !notice && <p role="status">正在读取任务…</p>
      )}
    </>
  );
}

function FileResourcePreview({ resource }: { resource: PreviewResource }) {
  const audio = useCompanionAudio();
  const [text, setText] = useState('');
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(true);
  const [start, setStart] = useState(1);
  const [page, setPage] = useState(1);
  const textArtifact = resource.kind === 'artifact' && /\.(md|txt)$/i.test(resource.title);
  useEffect(() => {
    const abort = new AbortController();
    setBusy(true);
    setNotice('');
    async function load() {
      try {
        if (textArtifact) {
          const response = await fetch(`/api/work/artifacts/${encodeURIComponent(resource.id)}`, {
            signal: abort.signal,
          });
          if (!response.ok) throw new Error('成果文件暂不可读取，请检查文件和授权。');
          const result = await response.text();
          if (!abort.signal.aborted) setText(result);
        } else {
          const result = await request<Record<string, unknown>>(
            `/work/${resource.kind === 'artifact' ? 'artifacts' : 'files'}/${encodeURIComponent(resource.id)}/preview?start=${start}`,
            { signal: abort.signal },
          );
          if (!abort.signal.aborted) setDocument(result);
        }
      } catch (error) {
        if (!abort.signal.aborted) setNotice((error as Error).message);
      } finally {
        if (!abort.signal.aborted) setBusy(false);
      }
    }
    void load();
    return () => abort.abort();
  }, [resource.id, resource.kind, start, textArtifact]);
  const pdf = /\.pdf$/i.test(resource.title);
  const image = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i.test(resource.title);
  return (
    <div className="file-preview">
      {busy && <p role="status">正在读取预览…</p>}
      {notice && <p role="status">{notice}</p>}
      {textArtifact ? (
        <>
          {audio && (
            <Button disabled={busy || !text} onClick={() => audio.enqueueDocument(text, resource.title)}>
              朗读完整总结
            </Button>
          )}
          <DocumentMarkdown text={text} />
        </>
      ) : (
        <>
          {resource.kind !== 'artifact' && (image || pdf) && (
            <img
              loading="lazy"
              src={`/api/work/files/${encodeURIComponent(resource.id)}/image?page=${page}`}
              alt={pdf ? `${resource.title} 第 ${page} 页` : resource.title}
            />
          )}
          {pdf && (
            <label className="field">
              预览页码
              <Input
                type="number"
                min={1}
                max={Number(document?.total_units ?? 1)}
                value={page}
                onChange={(event) =>
                  setPage(
                    Math.max(
                      1,
                      Math.min(Number(document?.total_units ?? 1), Number(event.target.value) || 1),
                    ),
                  )
                }
              />
            </label>
          )}
          {document && <DocumentResult result={document} />}
          {typeof document?.next_start === 'number' && (
            <Button disabled={busy} onClick={() => setStart(document.next_start as number)}>
              继续预览后续内容
            </Button>
          )}
        </>
      )}
      {resource.kind === 'artifact' && (
        <a
          className="text-link"
          href={
            resource.kind === 'artifact'
              ? `/api/work/artifacts/${encodeURIComponent(resource.id)}`
              : `/api/work/files/${encodeURIComponent(resource.id)}`
          }
          download
        >
          下载成果
        </a>
      )}
    </div>
  );
}
