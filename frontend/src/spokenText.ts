/** Withhold ambiguous line prefixes so a split opening fence never reaches TTS. */
export class SpokenTextFilter {
  private prefix = '';
  private ordinary = false;
  private indented = false;
  private fence = '';
  private fenceLength = 0;
  private opening = false;
  private html = '';
  private htmlTail = '';

  push(text: string): string {
    let output = '';
    for (const char of text) {
      if (this.html) {
        this.htmlTail = (this.htmlTail + char).slice(-30);
        if (new RegExp(`</${this.html}\\s*>$`, 'i').test(this.htmlTail)) {
          this.html = '';
          this.htmlTail = '';
          this.prefix = '';
          this.ordinary = false;
        }
        continue;
      }
      if (char === '\n') {
        const line = this.normalized();
        if (this.fence) {
          if (this.opening) {
            const match = line.match(/^ {0,3}(`{3,}|~{3,})/);
            if (match) this.fenceLength = match[1].length;
            this.opening = false;
          } else if (new RegExp(`^ {0,3}${this.fence}{${this.fenceLength},}\\s*$`).test(line)) {
            this.fence = '';
            this.fenceLength = 0;
          }
        } else if (!this.indented) output += this.ordinary ? '\n' : this.prefix + '\n';
        this.prefix = '';
        this.ordinary = false;
        this.indented = false;
        continue;
      }
      if (this.fence) {
        if (this.prefix.length < 1024) this.prefix += char;
        continue;
      }
      if (this.indented) continue;
      if (this.ordinary) {
        output += char;
        continue;
      }
      this.prefix += char;
      const line = this.normalized();
      if (/^( {4}|\t)/.test(line)) {
        this.indented = true;
        continue;
      }
      const fence = line.match(/^ {0,3}(`{3,}|~{3,})/);
      if (fence) {
        this.fence = fence[1][0];
        this.fenceLength = fence[1].length;
        this.opening = true;
        continue;
      }
      if (/^ {0,3}<(pre|code|tool_call)(?:\s[^>]*)?>$/i.test(line)) {
        this.html = line.match(/<(pre|code|tool_call)/i)![1];
        this.prefix = '';
        continue;
      }
      if (/^ {0,3}(?:`{0,2}|~{0,2}|<[^>]*|(?:> ?)+)?$/.test(line)) continue;
      this.ordinary = true;
      output += this.prefix;
      this.prefix = '';
    }
    return output;
  }
  private normalized() {
    return this.prefix.replace(/^ {0,3}(?:> ?)+/, '');
  }
  finish(): string {
    const tail = this.fence || this.indented || this.html || this.ordinary ? '' : this.prefix;
    this.prefix = '';
    return tail;
  }
}

export function spokenText(text: string) {
  const filter = new SpokenTextFilter();
  return filter.push(text) + filter.finish();
}
