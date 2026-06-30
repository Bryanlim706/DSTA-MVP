import { useRef, useState } from 'react'
import { uploadProject } from '../api/client'

interface Props {
  onUploadComplete: (jobId: string) => void
}

export default function UploadPage({ onUploadComplete }: Props) {
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [requirements, setRequirements] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [useRequirementsBox, setUseRequirementsBox] = useState(false)
  const [useReadme, setUseReadme] = useState(true)

  function handleRequirementsChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value
    setRequirements(val)
    if (val.trim().length > 0) setUseRequirementsBox(true)
    else setUseRequirementsBox(false)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file?.name.endsWith('.zip')) {
      setZipFile(file)
      setError(null)
    } else {
      setError('Please drop a .zip file')
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) {
      setZipFile(file)
      setError(null)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!zipFile) return setError('Please select a zip file')

    setUploading(true)
    setError(null)
    try {
      const jobId = await uploadProject(zipFile, requirements, {
        useRequirementsBox,
        useReadme,
      })
      onUploadComplete(jobId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
      setUploading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-start justify-center pt-16 px-4">
      <div className="w-full max-w-2xl">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold text-gray-900">Upload</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Zip upload */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Project codebase <span className="text-gray-400 font-normal">(.zip)</span>
            </label>
            <div
              className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                dragOver
                  ? 'border-blue-400 bg-blue-50'
                  : zipFile
                  ? 'border-green-400 bg-green-50'
                  : 'border-gray-300 hover:border-gray-400 bg-white'
              }`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={handleFileChange}
              />
              {zipFile ? (
                <div className="text-green-700">
                  <div className="text-2xl mb-1">✓</div>
                  <div className="font-medium">{zipFile.name}</div>
                  <div className="text-sm text-green-600 mt-1">
                    {(zipFile.size / 1024).toFixed(0)} KB — click to change
                  </div>
                </div>
              ) : (
                <div className="text-gray-400">
                  <div className="text-3xl mb-2">📁</div>
                  <div className="text-sm">Drop your zip here or click to browse</div>
                </div>
              )}
            </div>
          </div>

          {/* Requirements */}
          <div className="mt-10">
            <p className="text-sm font-medium text-gray-700 mb-2">
              Project requirements are found in
            </p>
            <div className="mb-3 flex gap-5">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={useReadme}
                  onChange={(e) => setUseReadme(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-500">README.md</span>
              </label>
            </div>
            <label className="mt-5 mb-2 flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={useRequirementsBox}
                onChange={(e) => setUseRequirementsBox(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-500">Requirements box</span>
            </label>
            <textarea
              value={requirements}
              onChange={handleRequirementsChange}
              placeholder="Paste requirements, user stories, or a plain description of intended functionality. Leave blank to rely on docs in the zip."
              rows={8}
              className={`w-full border border-gray-300 rounded-lg px-4 py-3 text-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition-opacity ${
                useRequirementsBox ? 'text-gray-900 opacity-100' : 'text-gray-400 opacity-40'
              }`}
            />
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={uploading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-medium py-3 px-6 rounded-lg transition-colors text-sm"
          >
            {uploading ? 'Uploading…' : 'Start Analysis'}
          </button>
        </form>
      </div>
    </div>
  )
}
