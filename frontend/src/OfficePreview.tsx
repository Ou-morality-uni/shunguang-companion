import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { GlideSelect } from '@/components/ui/glide-select';
import { request } from './api';
import type { PreviewResource } from './PreviewContext';
import { AnnotationTarget, type AnnotationAnchor } from './Annotations';
import { DocumentMarkdown } from './DocumentMarkdown';
import { useCompanionAudio } from './useAudioQueue';
import { ContinuousPreview } from './ContinuousPreview';

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
    <div className="workbook-preview">
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
                        <AnnotationTarget
                          anchor={prepare(target)}
                          prepare={async () => prepare(target)}
                          label={target.location}
                        >
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
      <details className="space-note workbook-notice">
        <summary>读取范围说明</summary>
        按工作表坐标展示已返回内容；公式显示原式，未返回的单元格以 — 标记，不代表原文件为空。
      </details>
    </div>
  );
}

export function OfficePreview({ resource }: { resource: PreviewResource }) {
  const [value, setValue] = useState<Resource | null>(null);
  const [error, setError] = useState('');
  const [limit, setLimit] = useState(50);
  const audio = useCompanionAudio();
  const image = /\.(png|jpe?g|webp|bmp|tiff?|gif)$/i.test(resource.title);
  const pages = /\.(pdf|docx|pptx)$/i.test(resource.title);
  const markdown = /\.(md|txt)$/i.test(resource.title);
  const base = `/work/resources/${resource.kind}/${encodeURIComponent(resource.id)}`;
  useEffect(() => {
    const abort = new AbortController();
    setValue(null);
    setError('');
    setLimit(50);
    void request<Resource>(base + (pages || image ? '/info' : '/targets'), { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) {
          if (!result || !Array.isArray(result.targets) || typeof result.version !== 'string')
            throw new Error('文件定位信息无效，请重新打开预览。');
          setValue(result);
        }
      })
      .catch((failure: Error) => {
        if (!abort.signal.aborted) setError(failure.message);
      });
    return () => abort.abort();
  }, [base, pages, image]);
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
  return (
    <div className="file-preview office-preview">
      {error && <p role="status">{error}</p>}
      {!value && !error && <p role="status">正在准备文件预览…</p>}
      {value && (pages || image) && (
        <ContinuousPreview
          key={`${base}:${value.version}`}
          image={image}
          url={`/api${base}/${image ? 'image' : 'document'}?version=${value.version}`}
          imageUrl={(page) => `/api${base}/image?page=${page}&version=${value.version}`}
          anchor={anchor({
            id: image ? 'image' : 'page:1',
            kind: image ? 'image' : 'page',
            text: '',
            location: image ? '整张图片' : '第 1 页',
          })}
        />
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
            <AnnotationTarget
              anchor={anchor(value.targets[0])}
              prepare={async () => anchor(value.targets[0])}
              label="文档正文"
            >
              <DocumentMarkdown text={value.targets[0].text} />
            </AnnotationTarget>
          )}
        </>
      )}
      {value && /\.xlsx$/i.test(resource.title) && (
        <>
          <WorkbookTargets targets={value.targets.slice(0, limit)} prepare={anchor} />
          {value.targets.length > limit && (
            <Button
              type="button"
              variant="outline"
              className="workbook-more"
              onClick={() => setLimit(limit + 50)}
            >
              显示更多对象
            </Button>
          )}
          {value.truncated && (
            <p className="space-note">当前工作表内容有范围限制；页面排版可通过导出 PDF 查看。</p>
          )}
        </>
      )}
      {resource.kind === 'artifact' && (
        <a className="text-link" href={`/api/work/artifacts/${encodeURIComponent(resource.id)}`} download>
          下载成果
        </a>
      )}
    </div>
  );
}
