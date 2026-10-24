import { useEffect, useState } from 'react';
import { request, type UserProfile } from './api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function UserProfileForm({ revision, onSaved }: { revision: string; onSaved: () => Promise<void> }) {
  const [profile, setProfile] = useState<UserProfile>({ nickname: '小师妹', city: '', age: null });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    void request<UserProfile>('/profile', { signal: abort.signal })
      .then((value) => {
        if (!abort.signal.aborted) setProfile(value);
      })
      .catch((error) => {
        if (!abort.signal.aborted) setNotice((error as Error).message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [revision]);
  async function save() {
    setBusy(true);
    setNotice('');
    try {
      setProfile(await request<UserProfile>('/profile', { method: 'PATCH', body: JSON.stringify(profile) }));
      await onSaved();
      setNotice('个人资料已保存，后续聊天和天气关怀会使用这些信息。');
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="user-profile-form glass"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2>关于你</h2>
      <fieldset disabled={loading || busy}>
        <label className="field">
          小光对你的称呼
          <Input
            required
            maxLength={40}
            value={profile.nickname}
            onChange={(event) => setProfile({ ...profile, nickname: event.target.value })}
          />
        </label>
        <label className="field">
          常住城市
          <Input
            maxLength={80}
            placeholder="例如：南宁；无需填写详细住址"
            value={profile.city}
            onChange={(event) => setProfile({ ...profile, city: event.target.value })}
          />
        </label>
        <label className="field">
          年龄（选填）
          <Input
            type="number"
            min={1}
            max={120}
            value={profile.age ?? ''}
            onChange={(event) =>
              setProfile({ ...profile, age: event.target.value === '' ? null : Number(event.target.value) })
            }
          />
        </label>
        <Button type="submit" disabled={!profile.nickname?.trim()}>
          保存个人资料
        </Button>
      </fieldset>
      <p className="space-note">
        明确的长期变化可在聊天中自动更新；临时出行会与常住信息区分。偏好记忆可在下方更正或删除。
      </p>
      {notice && <p role="status">{notice}</p>}
    </form>
  );
}
