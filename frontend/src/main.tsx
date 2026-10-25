import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './CompanionApp';
import './theme.css';
import './chat-preview.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
