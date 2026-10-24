import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlideSelect } from '@/components/ui/glide-select';
import { request } from './api';
import type { PreviewResource } from './PreviewContext';
import { AnnotationTarget, type AnnotationAnchor } from './Annotations';
import { DocumentMarkdown } from './DocumentMarkdown';
import { useCompanionAudio } from './useAudioQueue';
import { RegionAnnotation } from './RegionAnnotation';

type Target = { id: string; kind: string; text: string; location: string; page?: number; canvas?: number[] };
type Resource = {
  version: string;
  name: string;
  targets: Target[];
  truncated?: boolean;
  validation?: Record<string, string>;
};

function WorkbookTargets({
  targets,
  prepare,
}: {
  targets: Target[];
  prepare: (target: Target) => AnnotationAnchor;
}) {
  const sheets = [...new Set(targets.map((target) => target.id.split(':')[1]))];
  const [selected, setSelected] = useState(sheets[0] ?? '0');
  const visible = targets.filter((target) => target.id.split(':')[1] === selected);
  const name = visible[0]?.location.split(' · ')[0] ?? '工作表';
  const cells = visible.map((target) => ({
    target,
    column: target.id.split(':')[2].match(/^[A-Z]+/)?.[0] ?? '',
    row: Number(target.id.match(/[0-9]+$/)?.[0]),
  }));
  const columnNumber = (label: string) =>
    [...label].reduce((value, letter) => value * 26 + letter.charCodeAt(0) - 64, 0);
  const columns = [...new Set(cells.map((cell) => cell.column))].sort(
    (a, b) => columnNumber(a) - columnNumber(b),
  );
  const rows = [...new Set(cells.map((cell) => cell.row))].sort((a, b) => a - b);
  const mapping = new Map(cells.map((cell) => [`${cell.column}${cell.row}`, cell.target]));
  return (
    <>
      <label className="field">
        工作表
        <GlideSelect
          label="工作表"
          value={selected}
          onValueChange={setSelected}
          options={sheets.map((value) => ({
            value,
            label:
              targets.find((target) => target.id.split(':')[1] === value)?.location.split(' · ')[0] ?? value,
          }))}
        />
      </label>
      <div className="office-sheet-scroll">
        <table className="office-sheet" aria-label={`${name} 单元格内容预览`}>
          <thead>
            <tr>
              <th scope="col">行</th>
              {columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row}>
                <th scope="row">{row}</th>
                {columns.map((column) => {
                  const target = mapping.get(`${column}${row}`);
                  return (
                    <td key={column}>
                      {target ? (
                        <AnnotationTarget prepare={async () => prepare(target)} label={target.location}>
                          <div className="target-text">{target.text}</div>
                        </AnnotationTarget>
                      ) : (
                        <span aria-label="当前读取范围未返回此单元格">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="space-note">
        按工作表坐标展示已返回内容；公式显示原式，未返回的单元格以 — 标记，不代表原文件为空。
      </p>
    </>
  );
}

export function OfficePreview({ resource }: { resource: PreviewResource }) {
  const [value, setValue] = useState<Resource | null>(null);
  const [error, setError] = useState('');
  const [limit, setLimit] = useState(50);
  const [mode, setMode] = useState('content');
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [engine, setEngine] = useState(false);
  const audio = useCompanionAudio();
  const native = /\.(docx|xlsx|pptx)$/i.test(resource.title);
  const image = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i.test(resource.title);
  const pdf = /\.pdf$/i.test(resource.title);
  const markdown = /\.(md|txt)$/i.test(resource.title);
  const base = `/work/resources/${resource.kind}/${encodeURIComponent(resource.id)}`;
  useEffect(() => {
    const abort = new AbortController();
    setValue(null);
    setError('');
    setLimit(50);
    setPage(1);
    setMode(image || pdf ? 'pages' : 'content');
    void request<Resource>(base + '/targets', { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) {
          if (!result || !Array.isArray(result.targets) || typeof result.version !== 'string')
            throw new Error('文件定位信息无效，请重新打开预览。');
          setValue(result);
          setPages(Math.max(1, ...result.targets.map((target) => target.page ?? 1)));
        }
      })
      .catch((failure: Error) => {
        if (!abort.signal.aborted) setError(failure.message);
      });
    if (native)
      void request<{ office: { ready: boolean } }>('/work/capabilities', { signal: abort.signal })
        .then((result) => {
          if (!abort.signal.aborted) setEngine(result?.office?.ready === true);
        })
        .catch(() => {
          if (!abort.signal.aborted) setEngine(false);
        });
    return () => abort.abort();
  }, [base, image, native, pdf]);
  useEffect(() => {
    if (mode !== 'pages' || image || !value) return;
    const abort = new AbortController();
    void request<{ pages: number }>(base + '/pages?version=' + value.version, { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) setPages(result.pages);
      })
      .catch((failure: Error) => {
        if (!abort.signal.aborted) setError(failure.message);
      });
    return () => abort.abort();
  }, [base, mode, image, value]);
  function anchor(target: Target): AnnotationAnchor {
    return {
      source: {
        kind: resource.kind === 'artifact' ? 'artifact' : 'attachment',
        id: resource.id,
        version: value!.version,
      },
      target_id: target.id,
      name: value!.name,
      location: target.location,
    };
  }
  const pageTarget = value?.targets.find((target) => target.id === `page:${page}` || target.kind === 'image');
  return (
    <div className="file-preview office-preview">
      {error && <p role="status">{error}</p>}
      {!value && !error && <p role="status">正在读取文件内容与可批注位置…</p>}
      {native && (
        <>
          <label className="field">
            预览方式
            <GlideSelect
              label="预览方式"
              value={mode}
              onValueChange={(next) => {
                setError('');
                setMode(next);
              }}
              options={[
                { value: 'content', label: '内容与对象定位' },
                { value: 'pages', label: '页面排版预览', disabled: !engine },
              ]}
            />
          </label>
          {!engine && (
            <p className="space-note">
              页面预览需要 LibreOffice。
              <a
                href="https://www.libreoffice.org/download/download-libreoffice/"
                target="_blank"
                rel="noopener noreferrer"
              >
                查看安装说明
              </a>
              ；内容预览仍可使用。
            </p>
          )}
        </>
      )}
      {value && (mode === 'pages' || image) && (
        <>
          {(pdf || native) && (
            <label className="field">
              预览页码
              <Input
                type="number"
                min={1}
                max={pages}
                value={page}
                onChange={(event) => setPage(Math.min(pages, Math.max(1, Number(event.target.value) || 1)))}
              />
            </label>
          )}
          <RegionAnnotation
            key={`${resource.id}:${page}`}
            anchor={anchor(
              pageTarget ?? { id: `page:${page}`, kind: 'page', text: '', location: `第 ${page} 页` },
            )}
            src={`/api${base}/image?page=${page}&version=${value.version}`}
            alt={image ? value.name : `${value.name} 第 ${page} 页`}
            onError={() => setError('页面预览暂不可用，请检查文件、页码或 Office 引擎；仍可切回内容预览。')}
          />
        </>
      )}
      {value && markdown && (
        <>
          {audio && (
            <Button
              type="button"
              onClick={() => audio.enqueueDocument(value.targets[0]?.text ?? '', value.name)}
            >
              朗读完整内容
            </Button>
          )}
          {value.targets[0] && (
            <AnnotationTarget prepare={async () => anchor(value.targets[0])} label="文档正文">
              <DocumentMarkdown text={value.targets[0].text} />
            </AnnotationTarget>
          )}
        </>
      )}
      {value && /\.xlsx$/i.test(resource.title) && mode === 'content' && (
        <WorkbookTargets targets={value.targets.slice(0, limit)} prepare={anchor} />
      )}
      {value && !markdown && !image && !/\.xlsx$/i.test(resource.title) && (mode === 'content' || pdf) && (
        <div className="office-targets">
          {value.targets.slice(0, limit).map((target) => (
            <AnnotationTarget key={target.id} prepare={async () => anchor(target)} label={target.location}>
              <strong className="space-note">{target.location}</strong>
              <div className="target-text">{target.text || '〔空内容〕'}</div>
            </AnnotationTarget>
          ))}
        </div>
      )}
      {value && mode === 'content' && !markdown && !image && value.targets.length > limit && (
        <Button type="button" variant="outline" onClick={() => setLimit(limit + 50)}>
          显示更多对象
        </Button>
      )}
      {value?.truncated && (
        <p className="space-note">当前定位清单有范围限制，请缩小文件范围或使用原文件查看其余内容。</p>
      )}
      <a
        className="text-link"
        href={`/api/work/${resource.kind === 'artifact' ? 'artifacts' : 'files'}/${encodeURIComponent(resource.id)}`}
        download
      >
        下载{resource.kind === 'artifact' ? '成果' : '原文件副本'}
      </a>
    </div>
  );
}
