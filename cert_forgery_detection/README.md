Certificate Forgery Detection

Overview

Certificate Forgery Detection is a secure web-based application developed to verify the authenticity of academic certificates using blockchain technology, SHA-256 cryptographic hashing, QR code validation, and Optical Character Recognition (OCR). The system automates certificate verification, helping educational institutions and organizations detect forged or tampered certificates efficiently while reducing manual verification efforts.

Objectives

1. Verify certificates using QR code authentication.
2. Validate QR links against official issuing authorities.
3. Extract certificate information using OCR.
4. Generate SHA-256 hashes from certificate data.
5. Store certificate hashes securely on the blockchain.
6. Compare stored and generated hashes to detect certificate tampering.
7. Provide a fast, secure, and reliable certificate verification system.

Motivation

The increasing number of forged academic certificates has created significant challenges in educational institutions and recruitment processes. Manual verification is often slow and prone to errors. This project aims to provide a secure, scalable, and automated solution that ensures certificate authenticity using blockchain technology and cryptographic techniques.

Key Features

-> Secure user authentication
-> Digital certificate upload
-> OCR-based information extraction
-> QR code detection and validation
-> SHA-256 composite hash generation
-> Blockchain-based certificate verification
-> Certificate integrity checking
-> Tampering detection

Technologies Used

Frontend

-> HTML
-> CSS
-> JavaScript

Backend

-> Python
-> Flask

Blockchain

-> Ethereum
-> Web3.py
-> SHA-256 Hashing

Image Processing and OCR
-> OpenCV
-> EasyOCR / Tesseract OCR

Methodology

The system begins with secure user authentication, allowing only authorized users to upload or verify certificates.

For digitally generated certificates, the uploaded certificate is processed to extract important details such as the candidate's name, register number, and total marks. These details are combined into a single composite string, and a SHA-256 hash is generated. The generated hash is securely stored on the blockchain, creating a trusted reference for future verification.

During certificate verification, the uploaded certificate undergoes the same extraction process. A new SHA-256 hash is generated and compared with the previously stored blockchain hash. If both hashes match, the certificate is verified as authentic. If the hashes differ, the certificate is identified as modified or forged.

For scanned or printed certificates, the system extracts the embedded QR code and validates whether it redirects to the official issuing authority's website. OCR techniques are then used to extract certificate details, which are cross-verified to detect any inconsistencies. If mismatches are found, the certificate is flagged as potentially tampered or fraudulent.

Project Workflow

1. User Login
2. Upload Certificate
3. Extract Certificate Information
4. Generate SHA-256 Hash
5. Store or Retrieve Hash from Blockchain
6. Verify QR Code
7. Extract Data Using OCR
8. Compare Certificate Information
9. Display Verification Result

Security Features

-> Secure user authentication
-> Blockchain-based immutable storage
-> SHA-256 cryptographic hashing
-> QR code authentication
-> OCR-based certificate validation
-> Tampering detection

Demo:
https://drive.google.com/file/d/17op-NbnHzTQKBGZ2E2sTSnh5xrx1H5UR/view?usp=sharing

