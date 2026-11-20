// The firmware's ELF file as the rig loads it: the flash image and the symbol table.
//
// The ELF `pio run` builds holds everything a run needs, so no separate `.hex` file or symbol
// listing is made. Read as data, bounded: a file that is not a 32-bit little-endian AVR
// executable, or whose loadable parts do not fit the chip's flash, is refused whole.

export class ElfError extends Error {}

const EM_AVR = 83;
const PT_LOAD = 1;
const SHT_SYMTAB = 2;
const STT_NOTYPE = 0;
const STT_OBJECT = 1;
const STT_FUNC = 2;
// avr-gcc's linker script places each memory at its own offset in one address space: flash at
// 0, data memory at 0x800000, EEPROM at 0x810000; fuses, lock bits and the signature above.
const DATA_SPACE = 0x800000;
const EEPROM_SPACE = 0x810000;
const FUSE_SPACE = 0x820000;

function u16(view, at) {
  return view.getUint16(at, true);
}

function u32(view, at) {
  return view.getUint32(at, true);
}

function inside(bytes, offset, size) {
  return offset >= 0 && size >= 0 && offset + size <= bytes.length;
}

function cString(bytes, at, limit) {
  let end = at;
  while (end < limit && bytes[end] !== 0) end += 1;
  if (end >= limit) throw new ElfError('a symbol name runs past its string table');
  return new TextDecoder('latin1').decode(bytes.subarray(at, end));
}

/**
 * Load an AVR ELF executable.
 *
 * @param {Uint8Array} bytes the file's bytes
 * @param {{flashBytes: number, eepromBytes: number}} chip the target's memory sizes
 * @returns {{flash: Uint8Array, eeprom: Uint8Array | null, symbols: Map<string, {value: number, size: number, type: string}>}}
 */
export function loadElf(bytes, chip) {
  if (bytes.length < 52) throw new ElfError('the file is too short to be an ELF file');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes[0] !== 0x7f || bytes[1] !== 0x45 || bytes[2] !== 0x4c || bytes[3] !== 0x46) {
    throw new ElfError('the file is not an ELF file');
  }
  if (bytes[4] !== 1 || bytes[5] !== 1) {
    throw new ElfError('the file is not a 32-bit little-endian ELF file');
  }
  if (u16(view, 18) !== EM_AVR) throw new ElfError('the file is not built for an AVR');
  if (u16(view, 16) !== 2) throw new ElfError('the file is not an executable');

  const flash = new Uint8Array(chip.flashBytes).fill(0xff);
  let eeprom = null;
  const phoff = u32(view, 28);
  const phentsize = u16(view, 42);
  const phnum = u16(view, 44);
  if (phnum === 0 || phentsize < 32 || !inside(bytes, phoff, phentsize * phnum)) {
    throw new ElfError('the file has no readable program headers');
  }
  let loaded = 0;
  for (let i = 0; i < phnum; i += 1) {
    const at = phoff + i * phentsize;
    if (u32(view, at) !== PT_LOAD) continue;
    const offset = u32(view, at + 4);
    const paddr = u32(view, at + 12);
    const filesz = u32(view, at + 16);
    if (filesz === 0) continue; // .bss: cleared by the C runtime, nothing to load
    if (!inside(bytes, offset, filesz)) throw new ElfError('a segment lies outside the file');
    const content = bytes.subarray(offset, offset + filesz);
    if (paddr < DATA_SPACE) {
      if (paddr + filesz > chip.flashBytes) {
        throw new ElfError(`the program does not fit the chip's ${chip.flashBytes} bytes of flash`);
      }
      flash.set(content, paddr);
      loaded += filesz;
    } else if (paddr >= EEPROM_SPACE && paddr < FUSE_SPACE) {
      const start = paddr - EEPROM_SPACE;
      if (start + filesz > chip.eepromBytes) throw new ElfError('the EEPROM image does not fit');
      eeprom = eeprom ?? new Uint8Array(chip.eepromBytes).fill(0xff);
      eeprom.set(content, start);
    } else if (paddr < EEPROM_SPACE) {
      // Data memory with no load address in flash: a programmer could not write it.
      throw new ElfError('a segment with content is placed in data memory, not in flash');
    }
    // Fuses, lock bits and the signature are a programmer's, not the program's.
  }
  if (loaded === 0) throw new ElfError('the file loads nothing into flash');
  return { flash, eeprom, symbols: readSymbols(bytes, view) };
}

function readSymbols(bytes, view) {
  const symbols = new Map();
  const shoff = u32(view, 32);
  const shentsize = u16(view, 46);
  const shnum = u16(view, 48);
  if (shoff === 0 || shnum === 0) return symbols;
  if (shentsize < 40 || !inside(bytes, shoff, shentsize * shnum)) {
    throw new ElfError('the file has unreadable section headers');
  }
  for (let i = 0; i < shnum; i += 1) {
    const at = shoff + i * shentsize;
    if (u32(view, at + 4) !== SHT_SYMTAB) continue;
    const offset = u32(view, at + 16);
    const size = u32(view, at + 20);
    const link = u32(view, at + 24);
    const entsize = u32(view, at + 36) || 16;
    if (link >= shnum || entsize < 16 || !inside(bytes, offset, size)) {
      throw new ElfError('the symbol table is unreadable');
    }
    const strAt = shoff + link * shentsize;
    const strOffset = u32(view, strAt + 16);
    const strSize = u32(view, strAt + 20);
    if (!inside(bytes, strOffset, strSize)) throw new ElfError('the string table is unreadable');
    for (let s = offset; s + 16 <= offset + size; s += entsize) {
      const name = u32(view, s);
      const info = bytes[s + 12];
      const type = info & 0xf;
      // Functions and objects, and the linker's own untyped symbols (__heap_start, _end).
      if (name === 0 || (type !== STT_FUNC && type !== STT_OBJECT && type !== STT_NOTYPE)) continue;
      if (name >= strSize) throw new ElfError('a symbol names past its string table');
      const symbol = {
        value: u32(view, s + 4),
        size: u32(view, s + 8),
        type: type === STT_FUNC ? 'function' : type === STT_OBJECT ? 'object' : 'untyped',
        ambiguous: false,
      };
      const key = cString(bytes, strOffset + name, strOffset + strSize);
      const known = symbols.get(key);
      if (!known) symbols.set(key, symbol);
      else if (known.type === symbol.type && known.value !== symbol.value) known.ambiguous = true;
      else if (known.type !== 'function' && symbol.type === 'function') symbols.set(key, symbol);
    }
  }
  return symbols;
}
