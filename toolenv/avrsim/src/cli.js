// avrsim: the run environment's AVR simulator rig, from the command line.
//
//   avrsim --version
//   avrsim check --scenario s.json
//   avrsim run --elf firmware.elf --scenario s.json --out trace.jsonl
//
// `run` writes the cycle-stamped trace to --out and the summary beside it (the same name with
// `.summary.json` for its `.jsonl`), and prints the summary. It reads its two inputs and writes
// those two files, nothing else, and needs no network. Exit status: 0 done, 2 an input or an
// argument refused (nothing written), 1 the rig failed.

import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, openSync, readFileSync, readSync, writeSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

import { ElfError, loadElf } from './elf.js';
import { MAX_SCENARIO_BYTES, ScenarioError, readScenario } from './scenario.js';

// The simulator itself (avr8js, the chip, the board) is loaded only by `run`: the version line
// and a scenario's check read no more than they need.
let RigError = class extends Error {};

export const RIG_VERSION = '0.1.0';
const MAX_ELF_BYTES = 4 << 20;
const USAGE = `usage: avrsim --version
       avrsim check --scenario FILE
       avrsim run --elf FILE --scenario FILE --out TRACE.jsonl`;

class UsageError extends Error {}

function avr8jsVersion() {
  const path = new URL('../node_modules/avr8js/package.json', import.meta.url);
  return JSON.parse(readFileSync(path, 'utf8')).version;
}

function versionLine() {
  return `avrsim ${RIG_VERSION} avr8js ${avr8jsVersion()} node ${process.versions.node}`;
}

function options(args, allowed) {
  const found = {};
  for (let i = 0; i < args.length; i += 2) {
    const name = args[i];
    if (!allowed.includes(name)) throw new UsageError(`unknown argument ${JSON.stringify(name)}`);
    if (name in found) throw new UsageError(`${name} is given twice`);
    if (i + 1 >= args.length || args[i + 1].startsWith('--')) throw new UsageError(`${name} needs a value`);
    found[name] = args[i + 1];
  }
  for (const name of allowed) if (!(name in found)) throw new UsageError(`${name} is required`);
  return found;
}

/** A regular file's bytes, read through no link and bounded. */
function readBounded(path, limit, what) {
  let fd;
  try {
    fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  } catch (error) {
    throw new UsageError(`the ${what} ${path} cannot be opened as a plain file (${error.code})`);
  }
  try {
    const info = fstatSync(fd);
    if (!info.isFile()) throw new UsageError(`the ${what} ${path} is not a regular file`);
    if (info.size > limit) throw new UsageError(`the ${what} ${path} is larger than ${limit} bytes`);
    const bytes = Buffer.alloc(info.size);
    let read = 0;
    while (read < info.size) {
      const n = readSync(fd, bytes, read, info.size - read, read);
      if (n === 0) break;
      read += n;
    }
    return bytes.subarray(0, read);
  } finally {
    closeSync(fd);
  }
}

/** Open a file to write, created or emptied, never through a link. */
function openOutput(path) {
  try {
    return openSync(path, constants.O_WRONLY | constants.O_CREAT | constants.O_TRUNC | (constants.O_NOFOLLOW ?? 0), 0o644);
  } catch (error) {
    throw new UsageError(`the output ${path} cannot be written (${error.code})`);
  }
}

function summaryPath(out) {
  return out.endsWith('.jsonl') ? `${out.slice(0, -'.jsonl'.length)}.summary.json` : `${out}.summary.json`;
}

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

async function run(args) {
  const given = options(args, ['--elf', '--scenario', '--out']);
  const elfBytes = readBounded(given['--elf'], MAX_ELF_BYTES, 'ELF file');
  const scenarioBytes = readBounded(given['--scenario'], MAX_SCENARIO_BYTES, 'scenario');
  const scenario = readScenario(scenarioBytes.toString('utf8'));
  const { BOARD, BOARD_VERSION } = await import('./board.js');
  const { EEPROM_BYTES, FLASH_BYTES } = await import('./mcu.js');
  const rigModule = await import('./rig.js');
  const { Rig, Trace } = rigModule;
  RigError = rigModule.RigError;
  const elf = loadElf(new Uint8Array(elfBytes), { flashBytes: FLASH_BYTES, eepromBytes: EEPROM_BYTES });
  const out = given['--out'];
  const summaryFile = summaryPath(out);
  if (summaryFile === given['--elf'] || out === given['--elf'] || out === given['--scenario'] || summaryFile === given['--scenario']) {
    throw new UsageError('an output would overwrite an input');
  }
  const identity = {
    rig: { avrsim: RIG_VERSION, avr8js: avr8jsVersion(), node: process.versions.node, board: BOARD, board_version: BOARD_VERSION },
    elf_sha256: sha256(elfBytes),
    scenario_sha256: sha256(scenarioBytes),
  };
  let traceFd = null;
  const trace = new Trace((text) => writeSync(traceFd, text), scenario.trace.max_lines);
  const rig = new Rig(elf, scenario, trace); // refuses a probe the ELF does not hold
  traceFd = openOutput(out);
  const started = performance.now();
  let summary;
  try {
    trace.header({ type: 'header', avrsim_trace: 1, ...identity, frequency_hz: 16_000_000 });
    summary = { avrsim_summary: 1, ...identity, ...rig.run() };
  } finally {
    closeSync(traceFd);
  }
  const text = `${JSON.stringify(summary, null, 2)}\n`;
  const summaryFd = openOutput(summaryFile);
  try {
    writeSync(summaryFd, text);
  } finally {
    closeSync(summaryFd);
  }
  const wall = (performance.now() - started) / 1000;
  process.stderr.write(`avrsim: ${summary.simulated_s.toFixed(3)} s of board time in ${wall.toFixed(1)} s\n`);
  process.stdout.write(text);
}

export async function main(argv) {
  try {
    if (argv.length === 1 && argv[0] === '--version') {
      process.stdout.write(`${versionLine()}\n`);
      return 0;
    }
    if (argv[0] === 'check') {
      const given = options(argv.slice(1), ['--scenario']);
      readScenario(readBounded(given['--scenario'], MAX_SCENARIO_BYTES, 'scenario').toString('utf8'));
      process.stdout.write('the scenario is one avrsim reads\n');
      return 0;
    }
    if (argv[0] === 'run') {
      await run(argv.slice(1));
      return 0;
    }
    throw new UsageError(argv.length ? `unknown command ${JSON.stringify(argv[0])}` : 'no command');
  } catch (error) {
    if (error instanceof UsageError || error instanceof ScenarioError || error instanceof ElfError || error instanceof RigError) {
      process.stderr.write(`avrsim: ${error.message}\n${error instanceof UsageError ? `${USAGE}\n` : ''}`);
      return 2;
    }
    process.stderr.write(`avrsim: the rig failed: ${error?.stack ?? error}\n`);
    return 1;
  }
}

process.exitCode = await main(process.argv.slice(2));
