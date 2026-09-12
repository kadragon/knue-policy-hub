// Extracted from parse_preview.py so the table logic can be exercised against local
// HTML fixtures (tools/tests/test_extract_body.py) instead of only the live site.
// Evaluates to a function: (root: Element) => string.
(root) => {
    const BLOCK_TAGS = new Set([
        'P','DIV','LI','TR','TD','TH','CAPTION','ARTICLE','SECTION',
        'HEADER','FOOTER','H1','H2','H3','H4','H5','H6',
        'BLOCKQUOTE','PRE','THEAD','TBODY','TFOOT','BR',
    ]);
    // A cell's blocks are either stacked values (4.50 / 4.40-4.49 …), which need a
    // visible separator, or one label HWP wrapped mid-word. Only one shape tells the
    // two apart with certainty: a run of blocks that are each a single character is
    // 세로쓰기, never a list of values. Two multi-character blocks are ambiguous
    // (부처 + 국본부장 is a wrapped label, 합격 + 불합격 is two values), so they keep
    // the separator — splitting a label costs a grep, gluing two values loses data.
    function joinPieces(parts) {
        if (parts.length < 2) return parts.join('');
        const single = s => [...s].length === 1;
        const merged = [];
        let run = false;   // the last entry is a run of single-character blocks
        for (const s of parts) {
            if (run && single(s)) {
                merged[merged.length - 1] += s;   // 계 + 급 + 별 → 계급별
            } else {
                merged.push(s);
                run = single(s);
            }
        }
        // Never double a slash the source already wrote (학술지 + /출판사).
        return merged.reduce((acc, s) => !acc ? s
            : acc.endsWith('/') || s.startsWith('/') ? acc + s
            : acc + ' / ' + s, '');
    }
    function cellText(td) {
        // textContent glues stacked values together because <br> and block
        // boundaries inside a cell carry no character (4.50 + 4.40-4.49 →
        // "4.504.40-4.49"). Walk the cell and join the pieces with the same
        // ' / ' separator the header-band fold below uses.
        const parts = [];
        let buf = '';
        function flush() {
            const s = buf.replace(/\s+/g, ' ').trim();
            if (s) parts.push(s);
            buf = '';
        }
        function walkCell(node) {
            for (const child of node.childNodes) {
                if (child.nodeType === 3) { buf += child.nodeValue || ''; continue; }
                if (child.nodeType !== 1) continue;
                const ct = (child.tagName || '').toUpperCase();
                if (ct === 'SCRIPT' || ct === 'STYLE') continue;
                if (ct === 'BR') { flush(); continue; }
                if (BLOCK_TAGS.has(ct)) { flush(); walkCell(child); flush(); continue; }
                walkCell(child);
            }
        }
        walkCell(td);
        flush();
        return joinPieces(parts).replace(/\|/g, '\\|');
    }
    function collectRows(tbl) {
        const rows = [];
        for (const child of tbl.children) {
            const ct = (child.tagName || '').toUpperCase();
            if (ct === 'TR') {
                rows.push(child);
            } else if (ct === 'THEAD' || ct === 'TBODY' || ct === 'TFOOT') {
                for (const tr of child.children) {
                    if ((tr.tagName || '').toUpperCase() === 'TR') rows.push(tr);
                }
            }
        }
        return rows;
    }
    // Depth of a grouped header band at the top of the table, or 1 when there is
    // none. Fold only when the band is unambiguously a header: every row-0 cell
    // either spans the whole band or is a group (colspan) with labels below it,
    // the rows inside the band hold only non-empty, non-numeric labels under those
    // groups, and nothing in the band spills into the first body row. Anything
    // less certain stays unfolded, so a row-0 label that groups data rows (e.g.
    // 「1학년」 rowspan over course rows) is never swallowed into the header.
    // Known limit: HWP exports use TD only, so text-only data rows grouped under
    // a row-0 label (학부 → 입학원서/사진) are indistinguishable from sub-labels and
    // still fold — diff folded headers by hand when re-parsing.
    function headerDepth(head, src, full) {
        const depth = Math.max(1, ...head.map(h => h.rs));
        if (depth < 2 || depth >= full.length) return 1;
        if (head.some(h => h.rs !== depth && h.cs < 2)) return 1;
        const groupCols = new Set();
        for (const h of head) {
            if (h.rs < depth) for (let dc = 0; dc < h.cs; dc++) groupCols.add(h.c + dc);
        }
        if (!groupCols.size) return 1;
        for (let r = 1; r < depth; r++) {
            for (let c = 0; c < full[r].length; c++) {
                if (src[r][c] === 0) continue;
                if (!groupCols.has(c) || /^[\d\s.,%~+-]*$/.test(full[r][c])) return 1;
            }
        }
        if (src[depth].some(s => s !== depth)) return 1;
        return depth;
    }
    function extractTable(table) {
        const rows = collectRows(table);
        if (!rows.length) return '';
        // Expand rowspan/colspan into a grid, repeating the spanned text in every
        // slot it covers so each markdown row stays self-contained and columns line
        // up with multi-row headers. Without this, spanned cells shift left.
        const grid = [];
        const src = [];  // src[r][c]: row index where the cell covering (r, c) starts
        const srcc = []; // srcc[r][c]: column index where that cell starts
        const own = [];  // own[r]: row r starts a cell of its own that has text
        const opens = []; // opens[r]: cells row r starts, whatever their text
        const head = []; // row-0 cells: {c, rs, cs}
        rows.forEach((tr, r) => {
            grid[r] = grid[r] || [];
            src[r] = src[r] || [];
            srcc[r] = srcc[r] || [];
            let c = 0;
            for (const cell of tr.children) {
                const ct = (cell.tagName || '').toUpperCase();
                if (ct !== 'TD' && ct !== 'TH') continue;
                while (grid[r][c] !== undefined) c++;
                const text = cellText(cell);
                if (text) own[r] = true;
                opens[r] = (opens[r] || 0) + 1;
                const rs = Math.max(1, cell.rowSpan || 1);
                const cs = Math.max(1, cell.colSpan || 1);
                if (r === 0) head.push({c, rs, cs});
                for (let dr = 0; dr < rs && r + dr < rows.length; dr++) {
                    grid[r + dr] = grid[r + dr] || [];
                    src[r + dr] = src[r + dr] || [];
                    srcc[r + dr] = srcc[r + dr] || [];
                    for (let dc = 0; dc < cs; dc++) {
                        grid[r + dr][c + dc] = text;
                        src[r + dr][c + dc] = r;
                        srcc[r + dr][c + dc] = c;
                    }
                }
                c += cs;
            }
        });
        const full = grid.map(row => Array.from(row, v => v === undefined ? '' : v));
        // `full` repeats a spanned cell's text in every slot it covers, which is what the
        // header fold and the row-keep tests below need. Printing it would repeat the text
        // across the markdown row too (조 직 ×5), so the body prints `disp`: a colspan cell
        // shows at its origin column and the columns it covers stay blank. Rowspan keeps
        // repeating down, so each body row still reads on its own.
        const disp = full.map((row, r) => row.map((v, c) => srcc[r][c] === c ? v : ''));
        const depth = headerDepth(head, src, full);
        let data = [];
        const cols0 = Math.max(...full.map(row => row.length));
        if (depth > 1) {
            // Grouped header (e.g. 「하사관」 over 상사/중사/하사): markdown allows
            // one header row, so fold the band, joining each column's distinct labels.
            const width = Math.max(...full.slice(0, depth).map(r => r.length));
            const bandSpan = new Map();   // row-0 origin column → that cell's rowspan
            for (const h of head) bandSpan.set(h.c, h.rs);
            const folded = [];
            for (let c = 0; c < width; c++) {
                const parts = [];
                full.slice(0, depth).forEach((row, r) => {
                    // Repeating a group label onto its children is the point of the fold
                    // (하사관 / 상사, 하사관 / 중사). A row-0 cell that covers the whole
                    // band has no children below it, so repeating it just duplicates a
                    // header across the columns it spans (구 분 ×4) — print it at its
                    // origin column only, exactly like the body rows.
                    if (src[r][c] === 0 && srcc[r][c] !== c
                        && bandSpan.get(srcc[r][c]) === depth) return;
                    const v = row[c] || '';
                    if (v && !parts.includes(v)) parts.push(v);
                });
                folded.push(parts.join(' / '));
            }
            data.push(folded);
        }
        // Drop rows made only of span leftovers. An all-blank row survives only
        // when every one of its slots starts here — that is the fill-in space of a
        // 서식 table. A blank row that also carries columns spanned from above is
        // an HWP layout spacer, and keeping it duplicates the spanned data row.
        const bodyStart = depth > 1 ? depth : 0;
        full.forEach((row, r) => {
            if (r < bodyStart) return;
            const startsHere = Array.from({length: cols0}, (_, c) => src[r][c])
                .every(s => s === r);
            if (!(own[r] || (opens[r] && startsHere))) return;
            // A 서식 with twenty blank fill-in lines needs one blank row, not twenty.
            const blank = row.every(v => !v);
            if (blank && data.length && data[data.length - 1].every(v => !v)) return;
            data.push(disp[r]);
        });
        if (!data.length) return '';
        const cols = Math.max(...data.map(r => r.length));
        const norm = data.map(r => [...r, ...Array(cols - r.length).fill('')]);
        const mdLines = [];
        mdLines.push('| ' + norm[0].join(' | ') + ' |');
        mdLines.push('|' + Array(cols).fill('---').join('|') + '|');
        for (const row of norm.slice(1)) {
            mdLines.push('| ' + row.join(' | ') + ' |');
        }
        return '\n<<<TBL>>>\n' + mdLines.join('\n') + '\n<<</TBL>>>\n';
    }
    function walk(node) {
        if (node.nodeType === 3) return node.nodeValue || '';
        if (node.nodeType !== 1) return '';
        const tag = (node.tagName || '').toUpperCase();
        if (tag === 'SCRIPT' || tag === 'STYLE') return '';
        if (tag === 'TABLE') return extractTable(node);
        const isBlock = BLOCK_TAGS.has(tag);
        let text = isBlock ? '\n' : '';
        for (const child of node.childNodes) text += walk(child);
        if (isBlock) text += '\n';
        return text;
    }

    return walk(root);
}
