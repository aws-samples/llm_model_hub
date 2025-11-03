// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useMemo } from 'react';
import Anser from 'anser';

/**
 * Component to render ANSI escape codes as colored/styled text
 * Converts ANSI color codes like \033[36m to actual colors
 */
export const AnsiLog = ({ children, style = {}, debug = false }) => {
  const convertedText = useMemo(() => {
    if (!children) return null;

    let text = String(children);
    const originalText = text;

    // Convert #033 format to standard ANSI escape code \x1b
    // This handles cases where the escape character is displayed as #033
    text = text.replace(/#033/g, '\x1b');

    // Also handle other common escape sequence representations
    text = text.replace(/\\033/g, '\x1b');
    text = text.replace(/\\x1b/g, '\x1b');
    text = text.replace(/\\e/g, '\x1b');

    // Debug output in development mode
    if (debug && originalText !== text) {
      console.log('ANSI Conversion:', {
        original: originalText.substring(0, 100),
        converted: text.substring(0, 100),
        hasEscapeCodes: text.includes('\x1b')
      });
    }

    // Parse ANSI codes using anser
    const anserArray = Anser.ansiToJson(text, {
      use_classes: false,
      remove_empty: false
    });

    return anserArray.map((part, index) => {
      const inlineStyle = {};

      // Apply foreground color
      if (part.fg) {
        inlineStyle.color = `rgb(${part.fg})`;
      }

      // Apply background color
      if (part.bg) {
        inlineStyle.backgroundColor = `rgb(${part.bg})`;
      }

      // Apply text decorations
      if (part.decorations) {
        if (part.decorations.includes('bold')) {
          inlineStyle.fontWeight = 'bold';
        }
        if (part.decorations.includes('italic')) {
          inlineStyle.fontStyle = 'italic';
        }
        if (part.decorations.includes('underline')) {
          inlineStyle.textDecoration = 'underline';
        }
        if (part.decorations.includes('dim')) {
          inlineStyle.opacity = 0.5;
        }
      }

      return (
        <span key={index} style={inlineStyle}>
          {part.content}
        </span>
      );
    });
  }, [children]);

  return (
    <div style={{
      margin: 0,
      padding: '8px 12px',
      backgroundColor: '#0f1419',
      color: '#e6edf3',
      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: '12px',
      lineHeight: '1.6',
      overflowX: 'auto',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      borderBottom: '1px solid #21262d',
      ...style
    }}>
      {convertedText}
    </div>
  );
};

/**
 * Component to render logs line by line with ANSI support
 */
export const AnsiLogViewer = ({ logs, maxHeight = '500px' }) => {
  return (
    <div style={{
      maxHeight,
      overflowY: 'auto',
      border: '1px solid #d5dbdb',
      borderRadius: '4px'
    }}>
      {logs && logs.length > 0 ? (
        logs.map((log, index) => (
          <AnsiLog key={index}>{log}</AnsiLog>
        ))
      ) : (
        <AnsiLog>No logs available</AnsiLog>
      )}
    </div>
  );
};
