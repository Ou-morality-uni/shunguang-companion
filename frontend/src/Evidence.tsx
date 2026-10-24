import { ExternalLink, Wrench } from 'lucide-react';
import { safeSourceUrl, type Source, type ToolEvent, type HistorySource } from './api';
import { useResourcePreview } from './PreviewContext';

export function HistorySources({ sources = [] }: { sources?: HistorySource[] }) {
  const open = useResourcePreview();
  return sources.length ? (
    <details className="sources history-sources">
      <summary>回忆来源 · {sources.length} 条</summary>
      <div className="source-list">
        {sources.map((source) => (
          <article key={source.message_id} className="source-card">
            <strong>{source.title}</strong>
            <small>
              {source.role === 'user' ? '你当时说' : '当时的回复'} ·{' '}
              {new Date(source.time).toLocaleString('zh-CN')}
            </small>
            <p>{source.text}</p>
            <button
              type="button"
              className="text-link"
              disabled={!open}
              aria-label={`查看旧对话来源：${source.title}`}
              onClick={(event) =>
                open?.(
                  { kind: 'history', id: source.message_id, title: `旧对话 · ${source.title}` },
                  event.currentTarget,
                )
              }
            >
              查看来源原文
            </button>
          </article>
        ))}
      </div>
    </details>
  ) : null;
}
const verificationLabels: Record<string, string> = {
  official_verified: '官方资料已核实',
  official_account_text_crosschecked: '官方账号资料已交叉核对',
  official_verified_english_chinese_mapping_pending: '官方英文资料已核实，中文对应待核对',
  community_compilation_unverified: '社区整理 · 待核实',
  community_compilation_with_uncertainty: '社区整理 · 含存疑信息',
  uncertain_transcription: '听写存疑',
  fan_expansion: '同人扩展',
};

export function Sources({ sources = [] }: { sources?: Source[] }) {
  return sources.length ? (
    <details className="message-evidence">
      <summary>
        {sources.every((item) => item.usage === 'cited') ? '引用来源' : '参考资料'} · {sources.length} 条
      </summary>
      <div className="source-list">
        {sources.map((item, index) => {
          const url = safeSourceUrl(item.source_url || item.url);
          return (
            <article key={`${item.id || index}-${index}`} className="source-card">
              <strong>
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    {item.title || `来源 ${index + 1}`} <ExternalLink size={13} />
                  </a>
                ) : (
                  item.title || item.document_id || `资料 ${index + 1}`
                )}
              </strong>
              {(item.text || item.snippet) && <p>{item.text || item.snippet}</p>}
              <small>
                {[
                  item.verification_status
                    ? verificationLabels[item.verification_status] || item.verification_status
                    : '',
                  item.version,
                  item.spoiler ? '含剧透' : '',
                ]
                  .filter(Boolean)
                  .join(' · ') || '请结合原始来源核实'}
              </small>
            </article>
          );
        })}
      </div>
    </details>
  ) : null;
}
export function ToolFeedback({ tools = [] }: { tools?: ToolEvent[] }) {
  return tools.length ? (
    <div className="tool-feedback" aria-live="polite">
      {tools.map((item, index) => {
        const result =
          item.result && typeof item.result === 'object' ? (item.result as Record<string, unknown>) : null;
        const sources = result && Array.isArray(result.sources) ? (result.sources as Source[]) : [];
        const names: Record<string, string> = {
          weather: '天气查询',
          web_search: '网页搜索',
          remember_user_fact: '记住这件事',
          recall_conversations: '回忆聊天',
          workspace_files: '安排文件任务',
          workspace_task: '查看或取消文件任务',
        };
        return (
          <details key={item.id || index} className={`tool-call ${item.status === 'error' ? 'failed' : ''}`}>
            <summary>
              <Wrench size={14} />
              {names[item.name || ''] || item.name || item.tool || '工具调用'}
              <span>
                {item.status === 'running'
                  ? '执行中'
                  : result?.needs_clarification === true
                    ? '待补充信息'
                    : result?.code === 'no_results'
                      ? '无匹配结果'
                      : result?.code === 'low_relevance'
                        ? '结果不相关'
                        : item.status === 'error'
                          ? '调用失败'
                          : item.status === 'success' || item.status === 'complete'
                            ? result?.ok === false
                              ? '无可用结果'
                              : '已返回'
                            : item.status || '已返回'}
              </span>
            </summary>
            {item.message && <p>{item.message}</p>}
            <ToolResult result={result} />
            <Sources sources={sources} />
          </details>
        );
      })}
    </div>
  ) : null;
}
function ToolResult({ result }: { result: Record<string, unknown> | null }) {
  if (!result) return null;
  const message =
    typeof result.message === 'string'
      ? result.message
      : typeof result.error === 'string'
        ? result.error
        : '';
  const current =
    result.current && typeof result.current === 'object' ? (result.current as Record<string, unknown>) : null;
  const location =
    result.location && typeof result.location === 'object'
      ? (result.location as Record<string, unknown>)
      : null;
  const units =
    result.units && typeof result.units === 'object' ? (result.units as Record<string, unknown>) : null;
  return (
    <div className="tool-result-content">
      {message && <p>{message}</p>}
      {result.ok === true && current && (
        <>
          <strong>
            {String(location?.city || '当前城市')} · {String(result.condition || '天气')}
          </strong>
          <div className="weather-reading">
            {String(current.temperature_2m ?? '—')}
            <small>{String(units?.temperature_2m || '°C')}</small>
          </div>
          <p>
            体感 {String(current.apparent_temperature ?? '—')}
            {String(units?.apparent_temperature || '°C')} · 湿度 {String(current.relative_humidity_2m ?? '—')}
            % · 风速 {String(current.wind_speed_10m ?? '—')}
            {String(units?.wind_speed_10m || 'km/h')}
          </p>
          <p>
            数据时间：{String(current.time || '—')}（{String(result.timezone || '当地时区')}）
          </p>
        </>
      )}
      {result.ok === true && result.tool === 'web_search' && (
        <p>
          检索“{String(result.query || '关键词')}” · {String(result.provider || '网页服务')}
        </p>
      )}
      {typeof result.notice === 'string' && <p className="space-note">{result.notice}</p>}
    </div>
  );
}
