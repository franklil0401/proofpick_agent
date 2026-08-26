import '../global.css';
import 'remixicon/fonts/remixicon.css';
import { ClientRootProvider } from '@/components/providers/client-root-provider';
import { use } from 'react';
import type { ReactNode } from 'react';
import type { Translations } from 'fumadocs-ui/i18n';
import type { Metadata } from 'next';
import { i18n } from '@/lib/i18n';

// Generate static params for static export
export function generateStaticParams() {
  return i18n.languages.map((lang) => ({
    lang,
  }));
}

// Chinese translations
const zh: Partial<Translations> = {
  search: '搜索'
};


// Available language configurations
const locales = [
  {
    name: 'English',
    locale: 'en',
  },
  {
    name: '中文',
    locale: 'zh',
  },
];

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }) {
  // Resolve Promise to get language parameter
  const resolvedParams = await params;
  const { lang } = resolvedParams;
  
  // Set different titles and descriptions based on language
  const titles = {
    en: 'Youtu-RAG - An open-source multimodal RAG system for complex documents',
    zh: 'Youtu-RAG - 开源的多模态 RAG 系统，专注于复杂文档理解',
  };

  const descriptions = {
    en: 'Youtu-RAG is an open-source multimodal RAG system designed for complex document understanding. It provides advanced capabilities for parsing, chunking, embedding, and retrieving information from various document types including PDFs, images, Excel files, and databases.',
    zh: 'Youtu-RAG 是一个开源的多模态 RAG 系统，专注于复杂文档理解。提供先进的文档解析、分块、嵌入和检索能力，支持 PDF、图片、Excel、数据库等多种文档类型。',
  };

  const keywordsMap = {
    en: ['Youtu-RAG', 'RAG', 'Multimodal', 'Document Understanding', 'AI', 'Open Source', 'HiChunk', 'Embedding'],
    zh: ['Youtu-RAG', 'RAG', '多模态', '文档理解', 'AI', '开源', 'HiChunk', '向量嵌入'],
  } as const;

  const locales = {
    en: 'en_US',
    zh: 'zh_CN',
  };

  const title = titles[lang as keyof typeof titles] || titles.en;
  const description = descriptions[lang as keyof typeof descriptions] || descriptions.en;
  const keywords = keywordsMap[lang as keyof typeof keywordsMap] || keywordsMap.en;
  const locale = locales[lang as keyof typeof locales] || locales.en;

  return {
    title,
    description,
    keywords,
    icons: {
      icon: '/images/favicon.png',
      apple: '/images/favicon.png',
    },
    openGraph: {
      title,
      description,
      images: [
        {
          url: '/images/hello-adp.png',
          width: 1200,
          height: 630,
          alt: 'Youtu-RAG Logo',
        },
      ],
      locale,
      type: 'website',
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: ['/images/hello-adp.png'],
    },
  };
}

export default function Layout({ 
  children,
  params 
}: { 
  children: ReactNode;
  params: Promise<{ lang: string }>;
}) {
  const resolvedParams = use(params);
  const { lang } = resolvedParams;
  
  // Select translations based on language
  const translations = {
    zh
  }[lang];

  return (
    <ClientRootProvider
      i18n={{
        locale: lang,
        locales,
        translations
      }}
    >
      {children}
    </ClientRootProvider>
  );
}
