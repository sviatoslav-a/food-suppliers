#!/usr/bin/env python3
"""Record Scout's real Chromium UI, then encode a small, silent H.264 demo.

Run from the project root:
    uv run python tools/record_demo.py

Requires a running Scout server, Playwright Chromium, ffmpeg and ffprobe.
Only GET/HEAD requests reach Scout. Notes, shortlist and status changes live
in a disposable browser context, never in the supplier database. No mail,
telephone links, clipboard export, external navigation or supplier contact.
The visible pointer is recording instrumentation; application UI is unchanged.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

POINTER = r"""
(() => {
  const mount = () => {
    const pointer = document.createElement('div');
    pointer.setAttribute('aria-hidden', 'true');
    pointer.style.cssText = 'position:fixed;left:0;top:0;width:20px;height:26px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 1px 2px #0005)';
    pointer.innerHTML = '<svg width="20" height="26" viewBox="0 0 20 26"><path d="M2 2L2 21L7 16L11 24L15 22L11 14L18 14Z" fill="#15171a" stroke="white" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    let xy;
    try { xy = JSON.parse(sessionStorage.getItem('demo.pointer')); } catch {}
    const move = (x,y) => { pointer.style.transform = `translate(${x}px,${y}px)`; };
    move(...(xy || [1350, 850]));
    document.body.append(pointer);
    document.addEventListener('mousemove', e => {
      move(e.clientX, e.clientY);
      sessionStorage.setItem('demo.pointer', JSON.stringify([e.clientX,e.clientY]));
    });
  };
  document.addEventListener('DOMContentLoaded', mount, {once:true});
})();
"""


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--output-dir', type=Path, default=Path('docs/demo'))
    args = parser.parse_args()
    base = args.url.rstrip('/')
    origin = urlparse(base).netloc
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    for executable in ('ffmpeg', 'ffprobe'):
        if not shutil.which(executable):
            parser.error(f'{executable} is required')

    stages: list[dict] = []
    errors: list[str] = []
    # Raw videos and frame checks stay under docs/demo and are removed on exit.
    with tempfile.TemporaryDirectory(prefix='.recording-', dir=out) as work:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport={'width': 1440, 'height': 900},
                record_video_dir=work,
                record_video_size={'width': 1440, 'height': 900},
                device_scale_factor=1,
                color_scheme='light',
                locale='ru-RU',
                timezone_id='Europe/Moscow',
            )
            # Safety: the application is read-only; font downloads are allowed.
            def guard(route):
                req = route.request
                host = urlparse(req.url).netloc
                if req.method not in ('GET', 'HEAD') or host not in (
                    origin, 'fonts.googleapis.com', 'fonts.gstatic.com'
                ):
                    route.abort()
                else:
                    route.continue_()

            context.route('**/*', guard)
            context.add_init_script(POINTER)
            # Warm the real stylesheet/font cache in an unexported page so the
            # published take does not jump from fallback to downloaded fonts.
            warmup = context.new_page()
            warmup.goto(base, wait_until='networkidle')
            warmup.evaluate('document.fonts.ready')
            warmup.close()
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base, wait_until='load')
            page.evaluate('document.fonts.ready')
            health = context.request.get(base + '/healthz').json()
            assert health.get('ok') and health.get('suppliers') == 86, health
            video = page.video
            assert video is not None
            # Video time starts with Chromium's first captured frame, not page
            # creation. A small fixed lead avoids trimming the opening interaction.
            trim = 0.25
            started = time.monotonic()

            def at(seconds: float) -> None:
                remaining = seconds - (time.monotonic() - started)
                if remaining > 0:
                    page.wait_for_timeout(remaining * 1000)

            def stage(label: str) -> None:
                stages.append({'time': round(time.monotonic() - started, 2), 'stage': label})

            def point(locator) -> None:
                expect(locator).to_be_visible()
                box = locator.bounding_box()
                assert box is not None
                page.mouse.move(box['x'] + box['width'] / 2,
                                box['y'] + box['height'] / 2, steps=18)
                page.wait_for_timeout(160)

            def click(locator) -> None:
                point(locator)
                locator.click()

            def scroll_to(locator, top=100) -> None:
                locator.evaluate('''(el, top) => new Promise(resolve => {
                  const start = window.scrollY;
                  const end = Math.min(document.documentElement.scrollHeight - innerHeight,
                    Math.max(0, el.getBoundingClientRect().top + start - top));
                  const began = performance.now();
                  function frame(now) {
                    const t = Math.min(1, (now - began) / 650);
                    const ease = t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t+2,3)/2;
                    window.scrollTo(0, start + (end-start)*ease);
                    t < 1 ? requestAnimationFrame(frame) : resolve();
                  }
                  requestAnimationFrame(frame);
                })''', top)

            def park():
                page.mouse.move(1390, 855, steps=15)

            stage('Search')
            at(1.5)
            q = page.locator('[name=q]')
            click(q)
            q.press_sequentially('сыры для пиццы в Екатеринбурге с документами', delay=32)
            at(3.7)
            click(page.get_by_role('button', name='Найти', exact=True))
            expect(page.locator('[data-f=city]')).to_contain_text('Екатеринбург')
            at(4.7)
            scroll_to(page.locator('#results'), 90)
            park()
            at(6.4)
            gross = page.locator('[data-id="ekat-grossfood-ru"]')
            sobolev = page.locator('[data-id="sobolevcheese-ru"]')
            scroll_to(gross, 95)
            at(7.4)
            click(gross.locator('[data-compare]'))
            click(gross.locator('[data-shortlist]'))
            at(8.6)
            click(sobolev.locator('[data-compare]'))
            click(sobolev.locator('[data-shortlist]'))
            at(10)
            click(page.locator('[data-tray-go]'))
            expect(page.locator('[data-remove]')).to_have_count(2)
            stage('Compare two real suppliers')
            park()
            at(15)
            click(page.locator('thead a').filter(has_text='Гросс Фуд'))
            expect(page.locator('[data-supplier]')).to_have_attribute('data-supplier', 'ekat-grossfood-ru')
            stage('Supplier card and sourced terms')
            # Clear the completed comparison through the real UI, removing its tray.
            click(page.locator('[data-tray-clear]'))
            park()
            at(19)
            scroll_to(page.locator('#rfq'), 110)
            stage('Editable RFQ; no email sent')
            park()
            at(22)
            subject = page.locator('[data-rfq-subject]')
            click(subject)
            subject.fill('Запрос условий: моцарелла для пиццы, Екатеринбург')
            subject.press('Tab')
            park()
            at(26)
            scroll_to(page.locator('[data-mine-box]'), 125)
            stage('Browser-local notes and status')
            click(page.locator('[data-status=new]'))
            note = page.locator('[data-note]')
            click(note)
            note.press_sequentially('Уточнить MOQ и прайс на моцареллу.', delay=45)
            note.press('Tab')
            expect(page.locator('[data-status=new]')).to_have_attribute('aria-pressed', 'true')
            park()
            at(31.5)
            click(page.locator('[data-nav-shortlist]'))
            expect(page.locator('[data-item]')).to_have_count(2)
            expect(page.locator('[data-board]')).to_contain_text('Уточнить MOQ и прайс на моцареллу.')
            stage('Shortlist pipeline')
            park()
            at(34.5)
            move = page.locator('[data-move="sobolevcheese-ru"]')
            point(move)
            # A demo procurement decision, not a claim that a supplier replied.
            move.select_option('no')
            expect(page.locator('[data-col=no] [data-item="sobolevcheese-ru"]')).to_be_visible()
            park()
            at(39.5)
            assert not errors, errors
            context.close()
            raw = Path(video.path())
            browser.close()

        mp4 = out / 'scout-demo.mp4'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
             '-ss', f'{trim:.3f}', '-i', str(raw), '-t', '39.5',
             '-an', '-vf', 'fps=30', '-c:v', 'libx264', '-preset', 'slow',
             '-crf', '22', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
             str(mp4)])
        poster = out / 'scout-demo.jpg'
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
             '-ss', '12', '-i', str(mp4), '-frames:v', '1', '-q:v', '3', str(poster)])
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format',
            '-of', 'json', str(mp4)], text=True))
        stream = probe['streams'][0]
        duration = float(probe['format']['duration'])
        assert 25 <= duration <= 45, duration
        assert stream['codec_name'] == 'h264' and stream['pix_fmt'] == 'yuv420p'
        assert stream['r_frame_rate'] == '30/1'
        assert (stream['width'], stream['height']) == (1440, 900)
        assert mp4.stat().st_size <= 8_000_000
        summary = {
            'duration_seconds': duration,
            'codec': stream['codec_name'],
            'pixel_format': stream['pix_fmt'],
            'resolution': [1440, 900],
            'fps': 30,
            'mp4_bytes': mp4.stat().st_size,
            'poster_bytes': poster.stat().st_size,
            'stages': stages,
            'database_writes': False,
            'supplier_contact': False,
            'note': 'Disposable browser-local shortlist notes and rejection decision; no RFQ sent. Silent real Chromium recording; pointer overlay only.',
        }
        (out / 'scout-demo.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
