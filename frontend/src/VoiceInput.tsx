import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Mic, Square, X } from 'lucide-react';
import { request, type Features } from './api';
import { MAX_MESSAGE_LENGTH } from './generated/limits';
import { useCompanionAudio } from './useAudioQueue';

type Phase = 'idle' | 'acquiring' | 'recording' | 'transcribing';

export function VoiceInput({
  settings,
  disabled,
  onSettings,
  onBusyChange,
  composer,
}: {
  settings?: Features['asr'];
  disabled: boolean;
  onSettings: () => void;
  onBusyChange: (busy: boolean) => void;
  composer: { getState: () => { text: string }; setText: (text: string) => void };
}) {
  const audio = useCompanionAudio();
  const latest = useRef({ composer, audio, onBusyChange });
  latest.current = { composer, audio, onBusyChange };
  const [phase, setPhase] = useState<Phase>('idle'),
    [seconds, setSeconds] = useState(0),
    [notice, setNotice] = useState(''),
    [overflow, setOverflow] = useState('');
  const current = useRef<Phase>('idle'),
    generation = useRef(0);
  const recorder = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    abort = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  function change(value: Phase) {
    current.current = value;
    setPhase(value);
    latest.current.onBusyChange(value !== 'idle');
  }
  function release() {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    latest.current.audio.setInputActive(false);
  }
  function dispose() {
    generation.current++;
    abort.current?.abort();
    abort.current = null;
    const active = recorder.current;
    recorder.current = null;
    if (active && active.state !== 'inactive') active.stop();
    release();
  }
  useEffect(
    () => () => {
      dispose();
      latest.current.onBusyChange(false);
    },
    [],
  );
  function cancel(message = '已取消语音输入，草稿保持原样。') {
    dispose();
    change('idle');
    setNotice(message);
  }
  async function start() {
    if (current.current !== 'idle' || disabled) return;
    if (!settings?.enabled || !settings.configured) {
      onSettings();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setNotice('当前浏览器无法录音。请使用本机 localhost 或 HTTPS 页面，并允许麦克风权限。');
      return;
    }
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((item) =>
      MediaRecorder.isTypeSupported(item),
    );
    if (!mime) {
      setNotice('当前浏览器不支持可用的录音格式，请改用支持 WebM 或 MP4 录音的浏览器。');
      return;
    }
    const token = ++generation.current;
    setNotice('');
    setOverflow('');
    setSeconds(0);
    change('acquiring');
    latest.current.audio.setInputActive(true);
    try {
      const source = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (token !== generation.current) {
        source.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = source;
      const active = new MediaRecorder(source, { mimeType: mime });
      recorder.current = active;
      let bytes = 0;
      const chunks: Blob[] = [];
      active.ondataavailable = (event) => {
        if (token !== generation.current || !event.data.size) return;
        bytes += event.data.size;
        if (bytes > 10 * 1024 * 1024) {
          cancel('录音超过 10 MiB，已停止；请缩短后重试。');
          return;
        }
        chunks.push(event.data);
      };
      active.onerror = () => {
        if (token === generation.current) cancel('录音中断，请检查麦克风后重试。');
      };
      active.onstop = () => {
        if (token !== generation.current) return;
        recorder.current = null;
        release();
        change('transcribing');
        const controller = new AbortController();
        abort.current = controller;
        const media = (active.mimeType || mime).split(';')[0];
        void request<{ text: string }>('/asr/transcribe', {
          method: 'POST',
          body: new Blob(chunks, { type: media }),
          headers: { 'Content-Type': media },
          signal: controller.signal,
        })
          .then(({ text }) => {
            if (token !== generation.current) return;
            if (!text?.trim()) throw new Error('没有识别到文字，请重试。');
            const composer = latest.current.composer;
            const draft = composer.getState().text;
            const combined = draft ? draft + (draft.endsWith('\n') ? '' : '\n') + text : text;
            if (combined.length > MAX_MESSAGE_LENGTH) {
              setOverflow(text);
              setNotice(`识别文字和草稿合计超过 ${MAX_MESSAGE_LENGTH} 字，已保留识别文字供你复制。`);
            } else {
              composer.setText(combined);
              setNotice('识别文字已加入草稿，检查后再发送。');
            }
          })
          .catch((error: Error) => {
            if (token === generation.current && error.name !== 'AbortError') setNotice(error.message);
          })
          .finally(() => {
            if (token === generation.current) {
              abort.current = null;
              change('idle');
            }
          });
      };
      active.start(1000);
      change('recording');
      const began = Date.now();
      timer.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - began) / 1000);
        setSeconds(elapsed);
        if (elapsed >= 120 && active.state === 'recording') active.stop();
      }, 1000);
    } catch (error) {
      if (token === generation.current)
        cancel(
          (error as Error).name === 'NotAllowedError'
            ? '未获得麦克风权限。允许权限后可以重试，仍可继续输入文字。'
            : '麦克风无法启动，请检查设备或权限后重试。',
        );
    }
  }
  const label =
    phase === 'recording'
      ? '结束录音并转写'
      : phase === 'transcribing'
        ? '正在识别语音'
        : phase === 'acquiring'
          ? '正在申请麦克风'
          : '开始语音输入';
  return (
    <div className="voice-input">
      <button
        type="button"
        className={`icon-button ${phase === 'recording' ? 'recording' : ''}`}
        aria-label={label}
        title={label}
        disabled={phase === 'idle' ? disabled : phase !== 'recording'}
        onClick={() => (phase === 'recording' ? recorder.current?.stop() : void start())}
      >
        {phase === 'recording' ? (
          <Square size={16} />
        ) : phase === 'idle' ? (
          <Mic size={17} />
        ) : (
          <LoaderCircle size={17} className="spin" />
        )}
      </button>
      {phase !== 'idle' && (
        <button type="button" className="icon-button" aria-label="取消语音输入" onClick={() => cancel()}>
          <X size={14} />
        </button>
      )}
      {(phase !== 'idle' || notice) && (
        <span className="voice-input-notice" role="status">
          {phase === 'recording'
            ? `录音 ${seconds} 秒 · 最长 2 分钟`
            : phase === 'acquiring'
              ? '等待麦克风权限…'
              : phase === 'transcribing'
                ? '正在转成文字…'
                : notice}
        </span>
      )}
      {overflow && (
        <div className="voice-overflow">
          <textarea
            aria-label="未填入的识别文字"
            value={overflow}
            onChange={(event) => setOverflow(event.target.value)}
          />
          <button
            type="button"
            onClick={() =>
              void navigator.clipboard
                .writeText(overflow)
                .then(() => setNotice('识别文字已复制。'))
                .catch(() => setNotice('复制失败，请选中文字后手动复制。'))
            }
          >
            复制识别文字
          </button>
        </div>
      )}
    </div>
  );
}
