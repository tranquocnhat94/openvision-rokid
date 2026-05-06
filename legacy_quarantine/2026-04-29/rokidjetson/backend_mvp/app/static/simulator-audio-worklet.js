class RokidPcmTapProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const chunkFrames = Number(options?.processorOptions?.chunkFrames) || 4096;
    this.chunkFrames = Math.max(1024, chunkFrames);
    this.buffer = new Float32Array(this.chunkFrames);
    this.writeIndex = 0;
  }

  process(inputs) {
    const channel = inputs?.[0]?.[0];
    if (!channel || !channel.length) {
      return true;
    }

    let offset = 0;
    while (offset < channel.length) {
      const remaining = channel.length - offset;
      const space = this.buffer.length - this.writeIndex;
      const copyCount = Math.min(space, remaining);
      this.buffer.set(channel.subarray(offset, offset + copyCount), this.writeIndex);
      this.writeIndex += copyCount;
      offset += copyCount;

      if (this.writeIndex >= this.buffer.length) {
        const chunk = this.buffer.slice(0, this.writeIndex);
        this.port.postMessage({ type: "chunk", samples: chunk.buffer }, [chunk.buffer]);
        this.writeIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor("rokid-pcm-tap", RokidPcmTapProcessor);
