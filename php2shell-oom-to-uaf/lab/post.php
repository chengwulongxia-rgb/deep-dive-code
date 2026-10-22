<?php
/* Client used inside the container: POST a body, or GET, and print the result.
 *   post.php [--port N] [--get] [bodyfile] */
$port = 8080;
$get = false;
$file = null;
for ($i = 1; $i < $argc; $i++) {
    if ($argv[$i] === '--port') { $port = (int)$argv[++$i]; }
    elseif ($argv[$i] === '--get') { $get = true; }
    else { $file = $argv[$i]; }
}
$url = "http://127.0.0.1:$port/target.php";

if ($get) {
    $r = @file_get_contents($url, false, stream_context_create(['http' => [
        'ignore_errors' => true, 'timeout' => 10,
    ]]));
    echo $r === false ? "WORKER_UNRESPONSIVE\n" : $r;
    exit(0);
}

$body = file_get_contents($file);
$ctx = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => "Content-Type: multipart/form-data; boundary=---------------------------12345\r\n"
              . 'Content-Length: ' . strlen($body) . "\r\n",
    'content' => $body,
    'ignore_errors' => true,
    'timeout' => 30,
]]);
$r = @file_get_contents($url, false, $ctx);
$status = '000';
foreach (($http_response_header ?? []) as $h) {
    if (preg_match('#^HTTP/\S+\s+(\d+)#', $h, $m)) { $status = $m[1]; break; }
}
echo "HTTP=$status\n";
echo $r === false ? "REQUEST_FAILED\n" : $r;
