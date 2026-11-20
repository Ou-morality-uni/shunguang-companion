import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { request } from './api';

type ServiceState = {
  base_ready: boolean;
  qq_status: string;
  knowledge_ready: boolean;
  can_install_knowledge: boolean;
  knowledge_install: {
    state: string;
    stage: string | null;
    error: string | null;
  } | null;
};

export function ServiceManagement({ onVision, onQQ }: { onVision: () => void; onQQ?: () => void }) {
  const [status, setStatus] = useState<ServiceState | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [repair, setRepair] = useState(false);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const running = status?.knowledge_install?.state === 'running';

  useEffect(() => {
    const abort = new AbortController();
    const refresh = () => {
      void request<ServiceState>('/services/install', { signal: abort.signal })
        .then(setStatus)
        .catch((error: Error) => {
          if (!abort.signal.aborted) setNotice(error.message);
        });
    };
    refresh();
    const timer = running ? window.setInterval(refresh, 1500) : undefined;
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [running]);

  async function install() {
    setPending(true);
    setNotice('');
    try {
      const job = await request<NonNullable<ServiceState['knowledge_install']>>(
        '/services/install/knowledge',
        {
          method: 'POST',
          body: JSON.stringify({ confirmed: true }),
        },
      );
      setStatus((current) => (current ? { ...current, knowledge_install: job } : current));
      setConfirm(false);
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="服务管理">
      <h2>服务管理</h2>
      {notice && <p role="alert">{notice}</p>}
      <section>
        <h3>基础依赖</h3>
        <p>{status?.base_ready ? '项目正在运行' : '等待状态检查'}</p>
        <Button variant="outline" onClick={() => setRepair(!repair)}>
          修复基础
        </Button>
        {repair && <p>先正常关闭后端，再在项目目录运行 Install.bat。网页不会替换正在使用的环境。</p>}
      </section>
      <section>
        <h3>本地知识库</h3>
        <p role="status">
          {status?.knowledge_install?.error ??
            status?.knowledge_install?.stage ??
            (status?.knowledge_ready ? '可用，无需重启' : '未启用，不影响聊天')}
        </p>
        {status?.can_install_knowledge &&
          !status.knowledge_ready &&
          !running &&
          (confirm ? (
            <>
              <p>需要下载数 GB，建议预留至少 12 GiB 磁盘。校验成功后自动启用。</p>
              <Button disabled={pending} onClick={() => void install()}>
                确认安装
              </Button>
              <Button disabled={pending} variant="outline" onClick={() => setConfirm(false)}>
                取消
              </Button>
            </>
          ) : (
            <Button onClick={() => setConfirm(true)}>
              {status.knowledge_install?.error ? '重试安装' : '安装知识库'}
            </Button>
          ))}
        {status && !status.can_install_knowledge && <p>只能在 Windows 主机的本机模式下安装。</p>}
      </section>
      <section>
        <h3>识图</h3>
        <p>用支持图片的模型处理聊天中上传的图片，无需安装 OCR。</p>
        <Button variant="outline" onClick={onVision}>
          配置并测试视觉模型
        </Button>
      </section>
      <section>
        <h3>QQ 接入</h3>
        <p>{status?.qq_status === 'connected' ? '桥接已连接' : '桥接未连接或尚未配置'}</p>
        <a href="https://napneko.github.io/guide/boot/Shell" target="_blank" rel="noreferrer">
          NapCat 官方安装指南
        </a>
        {onQQ && (
          <Button variant="outline" onClick={onQQ}>
            配置与测试连接
          </Button>
        )}
      </section>
    </section>
  );
}
