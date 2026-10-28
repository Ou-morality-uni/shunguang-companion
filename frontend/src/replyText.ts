/** Legacy messages stay untouched in storage; protocol text is never replayed. */
export function visibleAssistantText(text: string): string {
  let fence = '';
  let inside = false;
  let output = '';
  for (let line of text.match(/[^\n]*\n|[^\n]+$/g) ?? []) {
    if (inside) {
      const end = line.toLowerCase().indexOf('</tool_call>');
      if (end < 0) continue;
      line = line.slice(end + 12);
      inside = false;
    }
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})([^\n]*)/);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length && !marker[2].trim()) fence = '';
    } else if (!fence && /^ {0,3}<tool_call>/i.test(line)) {
      output += '这次文件操作没有执行：模型未返回有效的工具调用，请重新发送请求。';
      const end = line.toLowerCase().indexOf('</tool_call>');
      inside = end < 0;
      line = inside ? '' : line.slice(end + 12);
    }
    output += line;
  }
  return output;
}
