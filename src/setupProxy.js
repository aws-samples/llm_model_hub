// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function(app) {
  // Get backend URL from environment variable or use default
  const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000';

  app.use(
    '/v1',
    createProxyMiddleware({
      target: backendUrl,
      changeOrigin: true,
      secure: false, // Accept self-signed certificates
      logLevel: 'debug',
      onProxyReq: function(proxyReq, req, res) {
        console.log(`[Proxy] ${req.method} ${req.url} -> ${backendUrl}${req.url}`);
      },
      onError: function(err, req, res) {
        console.error('[Proxy Error]', err);
        res.status(500).json({
          error: 'Proxy error',
          message: err.message
        });
      }
    })
  );
};
