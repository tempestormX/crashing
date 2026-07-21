/*
 * Local-only LSTM trainer for Equilibrium.
 * Inputs are cadence aggregates: median inter-key interval, variability,
 * correction rate, and long-pause rate. Typed text is never an input.
 */
(function () {
  const labels = ['steady', 'stretched', 'depleted'];
  const sequenceLength = 6;
  const modelUrl = 'indexeddb://equilibrium-personal-cadence-lstm-v1';
  const metadataKey = 'equilibrium-personal-cadence-lstm-metadata-v1';

  function buildSequences(samples) {
    const sequences = [];
    for (let index = sequenceLength - 1; index < samples.length; index += 1) {
      const window = samples.slice(index - sequenceLength + 1, index + 1);
      if (window.some(sample => !labels.includes(sample.label) || sample.features.length !== 4)) continue;
      sequences.push({ features: window.map(sample => sample.features), label: labels.indexOf(samples[index].label) });
    }
    return sequences;
  }

  function normalization(sequences) {
    const flat = sequences.flatMap(sequence => sequence.features);
    const means = [0, 1, 2, 3].map(feature => flat.reduce((sum, row) => sum + row[feature], 0) / flat.length);
    const deviations = [0, 1, 2, 3].map(feature => Math.sqrt(flat.reduce((sum, row) => sum + (row[feature] - means[feature]) ** 2, 0) / flat.length) || 1);
    return { means, deviations };
  }

  function normalizeSequences(sequences, scaler) {
    return sequences.map(sequence => sequence.features.map(row => row.map((value, index) => (value - scaler.means[index]) / scaler.deviations[index])));
  }

  async function train(samples, onProgress) {
    if (!window.tf) throw new Error('The local ML library did not load. Check your connection, then try again.');
    const sequences = buildSequences(samples);
    if (sequences.length < 12) throw new Error(`Need at least 12 labelled sequences; ${sequences.length} available.`);
    const classCounts = labels.map((_, index) => sequences.filter(sequence => sequence.label === index).length);
    if (classCounts.filter(Boolean).length < 2) throw new Error('Save check-ins from at least two different states before training.');
    const scaler = normalization(sequences);
    const xs = window.tf.tensor3d(normalizeSequences(sequences, scaler));
    const ys = window.tf.oneHot(window.tf.tensor1d(sequences.map(sequence => sequence.label), 'int32'), labels.length);
    const model = window.tf.sequential();
    model.add(window.tf.layers.lstm({ units: 16, inputShape: [sequenceLength, 4], dropout: .15, recurrentDropout: 0 }));
    model.add(window.tf.layers.dense({ units: 12, activation: 'relu' }));
    model.add(window.tf.layers.dense({ units: labels.length, activation: 'softmax' }));
    model.compile({ optimizer: window.tf.train.adam(.001), loss: 'categoricalCrossentropy', metrics: ['accuracy'] });
    try {
      await model.fit(xs, ys, {
        epochs: 24,
        batchSize: Math.min(8, sequences.length),
        validationSplit: sequences.length >= 20 ? .2 : 0,
        shuffle: true,
        callbacks: { onEpochEnd: async (epoch, logs) => onProgress?.(`Training locally: ${epoch + 1}/24 · loss ${logs.loss.toFixed(3)}`) }
      });
      await model.save(modelUrl);
      localStorage.setItem(metadataKey, JSON.stringify({ scaler, labels, sequenceLength, trainedAt: new Date().toISOString(), sequenceCount: sequences.length }));
      return { sequenceCount: sequences.length, classCounts };
    } finally {
      xs.dispose(); ys.dispose(); model.dispose();
    }
  }

  async function clear() {
    try {
      if (window.tf) await window.tf.io.removeModel(modelUrl);
      localStorage.removeItem(metadataKey);
    } catch (_) { /* It is fine if no model exists yet. */ }
  }

  async function predict(samples) {
    if (!window.tf) throw new Error('The local ML library did not load. Check your connection, then try again.');
    const metadata = JSON.parse(localStorage.getItem(metadataKey) || 'null');
    if (!metadata) throw new Error('Train a local model before checking a pattern.');
    if (samples.length < sequenceLength) throw new Error(`Save ${sequenceLength} or more check-ins before checking a pattern.`);
    const latest = samples.slice(-sequenceLength);
    const normalized = latest.map(sample => sample.features.map((value, index) => (value - metadata.scaler.means[index]) / metadata.scaler.deviations[index]));
    const model = await window.tf.loadLayersModel(modelUrl);
    const input = window.tf.tensor3d([normalized]);
    const output = model.predict(input);
    try {
      const probabilities = Array.from(await output.data());
      const bestIndex = probabilities.indexOf(Math.max(...probabilities));
      return { label: metadata.labels[bestIndex], confidence: probabilities[bestIndex], probabilities };
    } finally {
      input.dispose(); output.dispose(); model.dispose();
    }
  }

  window.EquilibriumLSTM = { labels, sequenceLength, train, predict, clear };
}());
