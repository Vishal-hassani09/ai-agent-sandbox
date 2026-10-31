import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

describe('App Component', () => {
  beforeEach(() => {
    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      const urlStr = String(url);

      if (urlStr.includes('/api/workspaces')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ workspaces: ['workspace', 'sandbox-alpha'] }),
        });
      }

      if (urlStr.includes('/api/workspace/files')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            files: ['calculator.py', 'main.py', 'src/utils.py'],
          }),
        });
      }

      if (urlStr.includes('/api/chat')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            response: 'Here is your generated code:\n```python\nprint("hello")\n```',
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled request: ${urlStr}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders initial UI elements and greeting message', async () => {
    render(<App />);

    expect(screen.getByText('Autonomous Coding Agent')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();

    // Match text fragment outside the parsed markdown <code> tag
    expect(
      screen.getByText(/to reference files, or ask me to inspect/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();

    // Wait for initial async state updates to populate options
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toHaveValue('workspace');
      expect(screen.getByRole('option', { name: 'sandbox-alpha' })).toBeInTheDocument();
    });
  });

  it('submits a user prompt, renders markdown response, and refocuses input', async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByPlaceholderText(/Type a prompt, or '@'/i);
    const sendButton = screen.getByRole('button', { name: /send/i });

    await user.type(input, 'Write a test file');
    expect(sendButton).not.toBeDisabled();

    await user.click(sendButton);

    expect(screen.getByText('Write a test file')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('print("hello")')).toBeInTheDocument();
    });

    expect(input).toHaveValue('');
    expect(input).toHaveFocus();
  });

  it('handles backend API errors gracefully in the chat feed', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Mock failing /api/chat call
    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      const urlStr = String(url);
      if (urlStr.includes('/api/chat')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: 'OpenAI rate limit exceeded' }),
        });
      }
      if (urlStr.includes('/api/workspaces')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ workspaces: ['workspace'] }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ files: [] }),
      });
    });

    const input = screen.getByPlaceholderText(/Type a prompt, or '@'/i);
    await user.type(input, 'Check health');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/⚠️ Error: OpenAI rate limit exceeded/i)
      ).toBeInTheDocument();
    });
  });

  it('triggers autocomplete popup when "@" is typed and injects selected file', async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByPlaceholderText(/Type a prompt, or '@'/i);

    // Wait for initial files fetch to populate
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/workspace/files')
      );
    });

    await user.type(input, 'Inspect @calc');

    expect(await screen.findByText('📄 calculator.py')).toBeInTheDocument();

    await user.click(screen.getByText('📄 calculator.py'));

    expect(input).toHaveValue('Inspect @calculator.py ');
    expect(screen.queryByText('Files in /workspace')).not.toBeInTheDocument();
  });

  it('clears conversation history when Clear button is clicked', async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByPlaceholderText(/Type a prompt, or '@'/i);
    await user.type(input, 'Temporary question');
    await user.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByText('Temporary question')).toBeInTheDocument();
    });

    const clearButton = screen.getByRole('button', { name: /clear/i });
    await user.click(clearButton);

    expect(screen.queryByText('Temporary question')).not.toBeInTheDocument();
    expect(
      screen.getByText(/to reference files, or ask me to inspect/i)
    ).toBeInTheDocument();
  });
});