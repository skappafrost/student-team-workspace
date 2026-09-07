'use client';

import * as React from 'react';
import { useState, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingButton } from '@/components/ui/loading-button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useUploadFile } from '../api/queries';

// Source: shadcn/ui Dialog + Input + Button; Tailwind CSS drag-and-drop zone pattern.
export function FileUploader() {
  const [open, setOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadFile();

  const handleFile = useCallback((file: File) => {
    setSelectedFile(file);
  }, []);

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(true);
  };

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      inputRef.current?.click();
    }
  };

  const onSubmit = async () => {
    if (!selectedFile) return;
    await upload.mutateAsync({ file: selectedFile });
    setSelectedFile(null);
    setOpen(false);
  };

  const onClose = (value: boolean) => {
    setOpen(value);
    if (!value) setSelectedFile(null);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogTrigger
        render={
          <Button type='button'>
            <Icons.add className='mr-2 h-4 w-4' />
            Upload file
          </Button>
        }
      />
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Upload file</DialogTitle>
          <DialogDescription>Choose a file or drag it into the drop zone below.</DialogDescription>
        </DialogHeader>
        <div
          role='button'
          tabIndex={0}
          aria-label='File drop zone'
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          onKeyDown={onKeyDown}
          className={cn(
            'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-8 transition-colors',
            dragActive
              ? 'border-primary bg-primary/5'
              : 'border-muted-foreground/25 hover:border-muted-foreground/50'
          )}
        >
          <Icons.upload className='h-10 w-10 text-muted-foreground' />
          <div className='text-center text-sm text-muted-foreground'>
            {selectedFile ? (
              <span className='font-medium text-foreground'>{selectedFile.name}</span>
            ) : (
              <>
                <span className='font-medium text-foreground'>Drag & drop</span> or click to choose
                a file
              </>
            )}
          </div>
          <Input ref={inputRef} type='file' className='sr-only' onChange={onInputChange} />
        </div>
        <DialogFooter showCloseButton>
          <LoadingButton
            type='button'
            onClick={onSubmit}
            disabled={!selectedFile}
            loading={upload.isPending}
          >
            Upload
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
