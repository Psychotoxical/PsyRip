"""rip_range mit simuliertem Laufwerk: Lesefehler, wackelnde Sektoren, Re-Read-Budget."""
import itertools

from psyrip import cdrip

SECTOR = cdrip.SECTOR


class FakeDrive:
    def __init__(self, unreadable=(), flaky=()):
        self.unreadable, self.flaky = set(unreadable), set(flaky)
        self.reads = 0
        self._noise = itertools.count(1)

    def read_sectors(self, lba, count):
        self.reads += 1
        out = bytearray()
        for s in range(lba, lba + count):
            if s in self.unreadable:
                raise OSError(23, "CRC error")
            if s in self.flaky:                       # liefert jedes Mal andere Daten
                out += next(self._noise).to_bytes(4, "little") * (SECTOR // 4)
            else:
                out += (s % 251).to_bytes(1, "little") * SECTOR
        return bytes(out)


def _disc(n=200):
    return cdrip.Disc([cdrip.Track(1, 0, n)], n, "X")


def test_clean_secure_rip():
    d = FakeDrive()
    pcm, bad, rr = cdrip.rip_range(d, _disc(), 0, 200, cdrip.RipOptions(cache_sectors=64))
    assert len(pcm) == 200 * SECTOR and bad == [] and rr == 0


def test_secure_reads_each_pass_sequentially_with_fine_progress():
    d = FakeDrive()
    calls = []
    orig = d.read_sectors
    d.read_sectors = lambda lba, n: (calls.append(lba), orig(lba, n))[1]
    prog = []
    cdrip.rip_range(d, _disc(2000), 0, 2000, cdrip.RipOptions(cache_sectors=64, chunk=26), prog.append)
    # zwei Durchläufe, jeder streng aufsteigend am Stück – genau ein Rücksprung dazwischen
    assert sum(1 for a, b in zip(calls, calls[1:]) if b < a) == 1
    assert len(prog) > 100 and prog == sorted(prog) and prog[-1] == 1.0


def test_unreadable_sector_does_not_abort_and_is_bad():
    for secure in (True, False):
        d = FakeDrive(unreadable={50})
        pcm, bad, _ = cdrip.rip_range(d, _disc(), 0, 200, cdrip.RipOptions(secure=secure, cache_sectors=64))
        assert len(pcm) == 200 * SECTOR
        assert bad == [50]
        assert pcm[51 * SECTOR:52 * SECTOR] == bytes([51]) * SECTOR


def test_reread_budget_caps_scratched_area():
    flaky = set(range(20, 120))                       # 100 nie übereinstimmende Sektoren
    d = FakeDrive(flaky=flaky)
    opt = cdrip.RipOptions(cache_sectors=64, max_rereads=20)
    _, bad, rr = cdrip.rip_range(d, _disc(), 0, 200, opt)
    assert bad == sorted(flaky)
    # ohne Budget wären es 100 * 20 = 2000 Re-Reads
    assert rr <= opt.max_rereads * 10 + 2 * len(flaky)
