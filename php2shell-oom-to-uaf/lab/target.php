<?php
/* Lab target: reports what the request parser actually handed to userland. */
header('Content-Type: text/plain');
printf("sapi=%s post=%d files=%d peak=%d\n",
    PHP_SAPI, count($_POST), count($_FILES), memory_get_peak_usage(true));
