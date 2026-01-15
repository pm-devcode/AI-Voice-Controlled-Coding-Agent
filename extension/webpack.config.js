const path = require('path');

/** @type {import('webpack').Configuration} */
const extensionConfig = {
  mode: 'development',
  target: 'node',
  entry: {
    extension: './src/extension.ts',
  },
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'extension.js',
    libraryTarget: 'commonjs',
    clean: true
  },
  resolve: {
    extensions: ['.ts', '.js']
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: [/node_modules/, /src\/test/],
        use: [
          { 
            loader: 'ts-loader',
            options: {
              onlyCompileBundledFiles: true
            }
          }
        ]
      }
    ]
  },
  externals: {
    vscode: 'commonjs vscode'
  },
  devtool: 'source-map'
};

/** @type {import('webpack').Configuration} */
const webviewConfig = {
  mode: 'development',
  target: 'web',
  entry: {
    webview: './src/webview/index.tsx'
  },
  output: {
    path: path.resolve(__dirname, 'dist'),
    filename: 'webview.js',
    libraryTarget: 'umd',
    globalObject: 'this',
    clean: false
  },
  resolve: {
    extensions: ['.ts', '.js', '.tsx', '.jsx']
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        exclude: [/node_modules/, /src\/test/],
        use: [
          {
            loader: 'ts-loader',
            options: {
              compilerOptions: {
                module: "es6"
              },
              onlyCompileBundledFiles: true
            }
          }
        ]
      },
      {
        test: /\.css$/,
        use: ['style-loader', 'css-loader']
      }
    ]
  },
  devtool: 'source-map'
};

module.exports = [extensionConfig, webviewConfig];

