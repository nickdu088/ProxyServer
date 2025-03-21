<?php
session_start();
// Set headers for CORS and content type
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: PUT, POST, DELETE");

// Get the HTTP method
$method = $_SERVER['REQUEST_METHOD'];

// Handle the request based on the HTTP method
switch ($method) {
    case 'PUT':
        // Handle PUT request
        handlePut();
        break;

    case 'POST':
        // Handle POST request
        handlePost();
        break;

    case 'DELETE':
        // Handle DELETE request
        handleDelete();
        break;
   
    case 'OPTIONS':
        echo '<pre>' . print_r($_SESSION, TRUE) . '</pre>';
        break;

    default:
        // Method not allowed
        http_response_code(405);
        echo json_encode(["message" => "Method Not Allowed"]);
        break;
}

// Function to handle PUT requests
function handlePut() {
    // Get the HTTP PUT parameters
    $id = basename($_SERVER['REQUEST_URI']);

    if ($id && isset($_SESSION[$id])) {
        // Read the binary body content
        $request = file_get_contents("php://input");
        if ($request) {
            $addr = $_SESSION[$id];
            // create persistent socket connection
            $connection = pfsockopen($addr['host'], $addr['port']);
            fwrite($connection, base64_decode($request));
            $response = '';
            $line = '';

            stream_set_timeout($connection, 2);
            while (!feof($connection)) {
                $line = fread($connection, 8192);
                if ($line === false || $line === '') {
                    break;
                }
                $response .= $line;
            }

            echo base64_encode($response);
            return;
        }
    }
    http_response_code(400);
}

// Function to handle POST requests
function handlePost() {
    // Get the input data
    $input = json_decode(file_get_contents("php://input"), true);
    if ($input && isset($input["host"]) && isset($input["port"]))
    {
        $id = uniqid();
        $_SESSION[$id] = $input;
        echo $id;
        return;
    }
    http_response_code(400); 
}

// Function to handle DELETE requests
function handleDelete() {
    $id = basename($_SERVER['REQUEST_URI']);
    if ($id && isset($_SESSION[$id])) {
        $addr = $_SESSION[$id];
        $connection = pfsockopen($addr['host'], $addr['port']);
        fclose($connection);
        unset($_SESSION[$id]);
        http_response_code(200); 
        return;
    }
    http_response_code(400);
}
?>
