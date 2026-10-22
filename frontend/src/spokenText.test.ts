import { expect, it } from 'vitest';
import { SpokenTextFilter, spokenText } from './spokenText';

const examples = [
  '开头。\n```python\nprint("hidden")\n```\n结尾。',
  '开头。\n```\nhidden plain text\n```\n结尾。',
  '开头。\n~~~json\n{"hidden":true}\n~~~\n结尾。',
  '开头。\n   ````txt\nhidden\n```\nmore hidden\n   ````\n结尾。',
  '开头。\n> ```bash\n> hidden command\n> ```\n结尾。',
  '开头。\n    hidden indented text\n结尾。',
  '开头。\n\thidden log\n结尾。',
  '开头。\n<pre>hidden\ntext</pre>\n结尾。',
];

it.each(examples)('excludes boxed content at every possible streaming boundary: %s', (raw) => {
  const expected = spokenText(raw);
  expect(expected).toContain('开头。');
  expect(expected).toContain('结尾。');
  expect(expected).not.toMatch(/hidden|print|```|~~~|bash|json/);
  for (let split = 0; split <= raw.length; split++) {
    const filter = new SpokenTextFilter();
    expect(filter.push(raw.slice(0, split)) + filter.push(raw.slice(split)) + filter.finish()).toBe(expected);
  }
  const filter = new SpokenTextFilter();
  expect(Array.from(raw, (char) => filter.push(char)).join('') + filter.finish()).toBe(expected);
});

it('never releases an unfinished fence and keeps ordinary text including inline code', () => {
  const filter = new SpokenTextFilter();
  expect(filter.push('先说。\n`')).toBe('先说。\n');
  expect(filter.push('`')).toBe('');
  expect(filter.push('`\nsecret')).toBe('');
  expect(filter.finish()).toBe('');
  expect(spokenText('可以调用 `hello()`，好啦~')).toBe('可以调用 `hello()`，好啦~');
});
