import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

describe('App Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        const urlStr = String(url);
        if (urlStr.includes('/api/workspace/files') || urlStr.includes('/files')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              files: ['backend/app/main.py', 'pyproject.toml'],
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'success',
            response: 'Here is your completed feature:\n\n```python\nprint("hello")\n```',
            session_id: 'test-session',
          }),
        });
      })
    );
  });

  it('renders initial UI elements and greeting message', () => {
    render(<App />);
    expect(screen.getByText(/Autonomous Coding Agent/i)).toBeInTheDocument();
    expect(screen.getByText(/Hello! Type/i)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Type a prompt, or '@' to reference files/i)
    ).toBeInTheDocument();
  });

  it('submits a user prompt, renders markdown response, and refocuses input', async () => {
    render(<App />);
    const input = screen.getByPlaceholderText(/Type a prompt, or '@' to reference files/i);
    const sendButton = screen.getByRole('button', { name: /Send/i });

    fireEvent.change(input, { target: { value: 'Create a hello world script' } });
    fireEvent.click(sendButton);

    expect(screen.getByText('Create a hello world script')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Here is your completed feature:/i)).toBeInTheDocument();
    });

    expect(document.activeElement).toBe(input);
  });

  it('handles backend API errors gracefully in the chat feed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url) => {
        const urlStr = String(url);
        if (urlStr.includes('/api/workspace/files') || urlStr.includes('/files')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ files: ['backend/app/main.py'] }),
          });
        }
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ detail: 'Internal sandboxing execution error' }),
        });
      })
    );

    render(<App />);
    const input = screen.getByPlaceholderText(/Type a prompt, or '@' to reference files/i);
    const sendButton = screen.getByRole('button', { name: /Send/i });

    fireEvent.change(input, { target: { value: 'Trigger backend error' } });
    fireEvent.click(sendButton);

    await waitFor(() => {
      expect(
        screen.getByText(/Internal sandboxing execution error/i)
      ).toBeInTheDocument();
    });
  });

  it('updates input value on typing and enables submit button', () => {
    render(<App />);
    const input = screen.getByPlaceholderText(/Type a prompt, or '@' to reference files/i);
    const sendButton = screen.getByRole('button', { name: /Send/i });

    expect(sendButton).toBeDisabled();

    fireEvent.change(input, { target: { value: 'Refactor test suite' } });

    expect(input.value).toBe('Refactor test suite');
    expect(sendButton).not.toBeDisabled();
  });

  it('clears conversation history when Clear button is clicked', () => {
    render(<App />);
    const input = screen.getByPlaceholderText(/Type a prompt, or '@' to reference files/i);

    fireEvent.change(input, { target: { value: 'Temporary message' } });
    const clearButton = screen.getByRole('button', { name: /Clear/i });

    fireEvent.click(clearButton);

    expect(screen.getByText(/Hello! Type/i)).toBeInTheDocument();
  });
});