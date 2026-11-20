import { useEffect, useState } from 'react';
import { request, type FileTask } from './api';
import { ArtifactCard } from './FileTasks';
import { Button } from '@/components/ui/button';

export function SavedFiles() {
  const [tasks, setTasks] = useState<FileTask[]>([]);
  const [notice, setNotice] = useState('正在读取历史成果…');
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void request<FileTask[]>(`/work/tasks?compact=true&artifacts_only=true&offset=${offset}`, {
      signal: abort.signal,
    })
      .then((items) => {
        setTasks(items);
        setNotice(items.length ? '' : offset ? '没有更多历史成果。' : '没有历史成果。');
      })
      .catch((error: Error) => {
        if (!abort.signal.aborted) setNotice(error.message);
      });
    return () => abort.abort();
  }, [offset]);
  return (
    <section className="glass">
      <h2>历史成果</h2>
      {notice && <p role="status">{notice}</p>}
      {tasks.map((task) => (
        <ArtifactCard key={task.id} task={task} />
      ))}
      {offset > 0 && (
        <Button variant="outline" onClick={() => setOffset(offset - 50)}>
          上一页
        </Button>
      )}
      {tasks.length === 50 && (
        <Button variant="outline" onClick={() => setOffset(offset + 50)}>
          下一页
        </Button>
      )}
    </section>
  );
}
